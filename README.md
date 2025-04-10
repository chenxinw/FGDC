# [Under Review] FGDC: A fine-grained divide-and-conquer approach for extending NCO to solve large-scale Traveling Salesman Problem

![overview](./overview.png)

This repository contains the implementation of our paper FGDC: A fine-grained divide-and-conquer approach for extending NCO to solve large-scale Traveling Salesman Problem.

## Highlights

* A divide-and-conquer approach is proposed to extend NCO to solve **large-scale TSP**.
* An **eﬀective dividing strategy** is proposed to construct small-scale sub-problems.
* An **MST-based merging strategy** is proposed for better solution quality.
* POMO trained on TSP-100 is employed to **solve TSP-1M**, achieving **optimal gap < 6%**.

## Dependencies

#### Main Dependency Packages

* [python](https://www.python.org) >= 3.8

* [pytorch](https://pytorch.org) >= 2.0.1

* [cuda](https://developer.nvidia.com/cuda-toolkit) >= 12.2

* [LKH](http://webhotel4.ruc.dk/~keld/research/LKH-3/) >= 3.0.7

* [tsplib95](https://github.com/rhgrant10/tsplib95)

* [pylkh](https://github.com/ben-hudson/pylkh)

* [mpire](https://github.com/sybrenjansen/mpire)

* [numpy](https://numpy.org)

* [tqdm](https://github.com/tqdm/tqdm#table-of-contents)

additional packages may be required to reproduce baselines

## Basic Usage

We provide codes of FGDC that utilizes POMO pre-trained on TSP-100 to solve REI / TSPLIB / VLSI instances.

```bash
python main.py
```
To run the comparative study, you need to specify the following parameters in `main.py`:
* `{method}`: 'extnco-eff'/ 'extnco-bal'/ 'extnco-qlt'/ 'htsp'/ 'pomo'/ 'deepaco'/ 'difusco'/ 'difusco-2opt'/ 'lkh'
* `{stage}`: 'first'/ 'second'
* `{dataset}`: 'rei'/ 'tsplib'/ 'vlsi'

## LKH
We provide source codes of [LKH-3.0.7](http://webhotel4.ruc.dk/~keld/research/LKH-3/), and **you need to install it first**. For example, on Ubuntu:
```bash
cd LKH-3.0.7/
make
```

## GCN-MCTS
This baseline method consists of two steps: 1) generate Heat Map using GCN model, and 2) generate and refine solution using MCTS.

The pre-trained GCN models are available at this [link](https://drive.google.com/file/d/1CXckcsThmJQNfhPGvJJ-oRhvo_vVp1d4/view?usp=sharing).

Rename the `tsp-models/tsp50/best_val_checkpoint.tar` file to **`tsp50.tar`**, and move it to the **`baselines/gcn_mcts/gcn/logs/`** folder.

#### step 1
```bash
python gcn_mcts_script.py
```
You need to specify the `{dataset}` parameter in `gcn_mcts_script.py`. The options include `'rei'`, `'tsplib'`, and `'vlsi'`.

#### step 2
We provide simple sripts for REI(-10K), TSPLib, and VLSI datasets.

Besides, remember to modify the **`baselines/gcn_mcts/code/TSP_IO.h`** file (lines 355-372) !!!

```bash
cd baselines/gcn_mcts/
bash solve.sh
```
