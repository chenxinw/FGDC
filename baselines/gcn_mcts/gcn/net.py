import os
import time
import math
import torch
import torch.nn as nn
import numpy as np
from scipy.spatial.distance import pdist
from scipy.spatial.distance import squareform
from sklearn.utils.class_weight import compute_class_weight
from baselines.gcn_mcts.gcn.config import get_config
from baselines.gcn_mcts.gcn.utils.tsplib import write_tsplib_prob
from baselines.gcn_mcts.gcn.data_generator import tsp_instance_reader
from baselines.gcn_mcts.gcn.models.gcn_model import ResidualGatedGCNModel


def load_model(model, device_ids):
    assert torch.cuda.is_available()
    torch.cuda.manual_seed_all(1)
    dtypeFloat = torch.cuda.FloatTensor
    dtypeLong = torch.cuda.LongTensor

    config_path = 'baselines/gcn_mcts/gcn/configs/{}.json'.format(model)
    config = get_config(config_path)

    net = nn.DataParallel(ResidualGatedGCNModel(config, dtypeFloat, dtypeLong), device_ids=device_ids).cuda()
    checkpoint = torch.load(f'baselines/gcn_mcts/gcn/logs/{model}.tar')
    net.load_state_dict(checkpoint['model_state_dict'])
    transform_1d(net)

    net.eval()
    return net


def copy_params(obj):
    in_dim = obj.in_channels
    out_dim = obj.out_channels
    bias = obj.bias.data.clone()
    weight = obj.weight.data.clone()

    return in_dim, out_dim, bias, weight


def transform_1d(net):  # transform nn.Con1d to nn.Conv2d
    for layer in net.module.gcn_layers:
        in_dim, out_dim, bias, weight = copy_params(layer.edge_feat.U)
        layer.edge_feat.U = nn.Conv2d(in_dim, out_dim, (1, 1))
        layer.edge_feat.U.bias.data = bias
        layer.edge_feat.U.weight.data = weight
    for cur_idx in range(net.module.mlp_layers - 1):
        in_dim, out_dim, bias, weight = copy_params(net.module.mlp_edges.U[cur_idx])
        net.module.mlp_edges.U[cur_idx] = nn.Conv2d(in_dim, out_dim, (1, 1))
        net.module.mlp_edges.U[cur_idx].bias.data = bias
        net.module.mlp_edges.U[cur_idx].weight.data = weight
    in_dim, out_dim, bias, weight = copy_params(net.module.mlp_edges.V)
    net.module.mlp_edges.V = nn.Conv2d(in_dim, out_dim, (1, 1))
    net.module.mlp_edges.V.bias.data = bias
    net.module.mlp_edges.V.weight.data = weight


# def build_map(model, scale, batch_size=16, K=50, K_expand=99, type=None, ins=None, device='cuda:0'):
def build_map(model, dataset, scale, ins, batch_size=16, K=50, K_expand=99, device='cuda:0'):
    # load tsp instances
    f = open(f'baselines/gcn_mcts/data/{dataset}/{ins}.txt', 'r')
    samples = f.readlines()
    sample_num = len(samples)
    f.close()

    # init parameters and variables
    buff_coord = np.zeros((scale, 2), dtype=np.float64)
    avg_mean_rank = []

    # sampling sub-graphs
    tt = time.time()
    for idx in range(sample_num):
        st = time.time()
        edge, edges_value, node, node_coord, edge_target, node_target, mesh, omega, opt = test_one_tsp(
                tsp_source=samples[idx], coord_buff=buff_coord, node_num=scale,
                cluster_center=0, top_k=K-1, top_k_expand=K_expand)
        x_edges = torch.Tensor(np.array(edge)).long().to(device)
        x_edges_values = torch.Tensor(np.array(edges_value)).float().to(device)
        x_nodes = torch.Tensor(np.array(node)).long().to(device)
        x_nodes_coord = torch.Tensor(np.array(node_coord)).float().to(device)
        y_edges = torch.Tensor(np.array(edge_target)).long().to(device)
        # y_nodes = torch.Tensor(np.array(node_target)).long().to(device)
        meshs = np.array(mesh)

        # Compute class weights
        edge_labels = y_edges.cpu().numpy().flatten()
        edge_cw = compute_class_weight("balanced", classes=np.unique(edge_labels), y=edge_labels)

        # generate heatmap for sub-graphs
        y_probs = np.zeros([0, 50, 50, 2]).astype(np.float32)
        sub_idx = 0
        while sub_idx < len(x_edges):
            srt = sub_idx
            end = srt + batch_size
            sub_y_preds = model.forward(x_edges[srt:end], x_edges_values[srt:end], x_nodes[srt:end],
                                        x_nodes_coord[srt:end], y_edges[srt:end], edge_cw)
            sub_y_probs = torch.softmax(sub_y_preds, dim=3).cpu().numpy()
            y_probs = np.concatenate((y_probs, sub_y_probs), axis=0)
            sub_idx += batch_size

        # merge heatmaps for each instance
        heatmap_path = f'baselines/gcn_mcts/heatmap/{dataset}/'
        heatmap_path += f'{ins}_{idx}.txt' if dataset == 'rei' else f'{scale}_0.txt'
        # rank = multiprocess_write(y_probs, meshs, Omegas[0], scale, heatmap_path, True, opts[0])
        rank = multiprocess_write(y_probs, meshs, omega, scale, heatmap_path, True, opt)
        avg_mean_rank.append(rank)
        print('build 1 heatmap for {} instance in {:.2f}s'.format(ins, time.time() - st))
    if sample_num > 1:
        tt = time.time() - tt
        print('build {} heatmaps in {:.2f}s, avg_time: {:.2f}s'.format(sample_num, tt, tt / sample_num))


def test_one_tsp(tsp_source, coord_buff, node_num=20, cluster_center=0, top_k=19, top_k_expand=19):
    mean_rank_sum, mean_greater_zero_edges = 0, 0
    # read node coords and solution by Concorde
    coord, opt = tsp_instance_reader(tspinstance=tsp_source, buff=coord_buff, num_node=node_num)
    coords = [coord]

    distA = pdist(coords[0], metric='euclidean')
    distB_raw = squareform(distA)
    distB = squareform(distA) + 10.0 * np.eye(N=node_num, M=node_num, dtype=np.float64)

    edges_probs = np.zeros((node_num, node_num), dtype=np.float64)

    pre_edges = np.ones((top_k + 1, top_k + 1), dtype=np.int32) + np.eye(N=top_k + 1, M=top_k + 1)
    pre_node = np.ones((top_k + 1,))

    pre_node_target = np.arange(0, top_k + 1)
    pre_node_target = np.append(pre_node_target, 0)
    pre_edge_target = np.zeros((top_k + 1, top_k + 1))
    pre_edge_target[pre_node_target[:-1], pre_node_target[1:]] = 1
    pre_edge_target[pre_node_target[1:], pre_node_target[:-1]] = 1

    neighbor = np.argpartition(distB, kth=top_k, axis=1)

    neighbor_expand = np.argpartition(distB, kth=top_k_expand, axis=1)
    Omega_w = np.zeros(node_num, dtype=np.int32)
    Omega = np.zeros((node_num, node_num), dtype=np.int32)

    edges, edges_values, nodes, nodes_coord, edges_target, nodes_target, meshs = [], [], [], [], [], [], []
    num_clusters = 0
    if node_num == 20:
        num_clusters_threshold = 1
    else:
        num_clusters_threshold = math.ceil((node_num / (top_k + 1)) * 5)
    all_visited = False
    num_batch_size = 0

    while num_clusters < num_clusters_threshold or all_visited == False:
        if all_visited == False:
            cluster_center_neighbor = neighbor[cluster_center, :top_k]
            cluster_center_neighbor = np.insert(cluster_center_neighbor, 0, cluster_center)
        else:
            np.random.shuffle(neighbor_expand[cluster_center, :top_k_expand])
            cluster_center_neighbor = neighbor_expand[cluster_center, :top_k]
            cluster_center_neighbor = np.insert(cluster_center_neighbor, 0, cluster_center)

        Omega_w[cluster_center_neighbor] += 1

        # case 4
        node_coord = coords[0][cluster_center_neighbor]
        x_y_min = np.min(node_coord, axis=0)
        scale = 1.0 / np.max(np.max(node_coord, axis=0) - x_y_min)
        node_coord = node_coord - x_y_min
        node_coord *= scale
        nodes_coord.append(node_coord)

        # case 1-2
        edges.append(pre_edges)
        mesh = np.meshgrid(cluster_center_neighbor, cluster_center_neighbor)

        edges_value = distB_raw[tuple(mesh)].copy()
        # edges_value = distB_raw[mesh].copy()
        edges_value *= scale
        edges_values.append(edges_value)
        meshs.append(mesh)
        # Omega[mesh] += 1
        Omega[tuple(mesh)] += 1

        # case 3
        nodes.append(pre_node)

        # case 5-6
        edges_target.append(pre_edge_target)
        nodes_target.append(pre_node_target[:-1])

        num_clusters += 1

        if 0 not in Omega_w:
            all_visited = True

        cluster_center = np.random.choice(np.where(Omega_w == np.min(Omega_w))[0])

    return edges, edges_values, nodes, nodes_coord, edges_target, nodes_target, meshs, Omega, opt


def multiprocess_write(sub_prob, meshgrid, omega, node_num=20, tsplib_name='./sample.txt', statiscs=False, opt=None):
    edges_probs = np.zeros((node_num, node_num), dtype=np.float32)
    for i in range(len(meshgrid)):
        edges_probs[tuple(meshgrid[i])] += sub_prob[i, :, :, 1]
    edges_probs = edges_probs / (omega + 1e-8)  # [:, None]
    # normalize the probability in an instance
    edges_probs = edges_probs + edges_probs.T
    edges_probs_norm = edges_probs / np.reshape(np.sum(edges_probs, axis=1), newshape=(node_num, 1))

    mean_rank = 0
    if statiscs:
        for i in range(node_num - 1):
            mean_rank += len(np.where(edges_probs_norm[opt[i], :] >= edges_probs_norm[opt[i], opt[i + 1]])[0])
        mean_rank /= (node_num - 1)

        false_negative_edge = opt[np.where(edges_probs_norm[opt[:-1], opt[1:]] < 1e-5)]
        num_fne = len(false_negative_edge)  # false negative edges in an instance
        greater_zero_edges = len(np.where(edges_probs_norm > 1e-6)[0]) / node_num

        write_tsplib_prob(tsplib_name, edge_prob=edges_probs_norm, num_node=node_num, mean=mean_rank,
                          fnn=num_fne, greater_zero=greater_zero_edges)
    else:
        write_tsplib_prob(tsplib_name, edge_prob=edges_probs_norm, num_node=node_num, mean=0,
                          fnn=0, greater_zero=0)
    return mean_rank
