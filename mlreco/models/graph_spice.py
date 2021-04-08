import torch
import torch_geometric
import numpy as np

from .cluster_cnn.losses.spatial_embeddings import *
from .cluster_cnn import (cluster_model_construct, 
                          spice_loss_construct,
                          gs_kernel_construct)

from .gnn import gnn_model_construct

from pprint import pprint
from mlreco.utils.cluster.graph_spice import (
    ClusterGraphConstructor, get_edge_weight)
from mlreco.utils.metrics import ARI


class GraphSPICE(nn.Module):
    '''
    Neighbor-graph embedding based particle clustering.

    GraphSPICE has two components:
        1) Voxel Embedder: UNet-type CNN architecture used for feature
        extraction and feature embeddings.

        2) Edge Probability Kernel function: A kernel function (any callable
        that takes two node attribute vectors to give a edge proability score).

    Prediction is done in two steps:
        1) A neighbor graph (ex. KNN, Radius) is constructed to compute 
        edge probabilities between neighboring edges. 
        2) Edges with low probability scores are dropped. 
        3) The voxels are clustered by counting connected components. 

    Parameters:
        - skip_classes: semantic labels for which to skip voxel clustering
        (ex. Michel, Delta, and Low Es rarely require neural network clustering)

        - dimension: dimension of input dataset. 
    '''

    def __init__(self, cfg, name='graph_spice'):
        super(GraphSPICE, self).__init__()
        print('--------------------CFG----------------------------')
        pprint(cfg)
        print('--------------------GraphSPICE---------------------')
        self.model_config = cfg[name]
        pprint(self.model_config)
        self.skip_classes = self.model_config.get('skip_classes', [2, 3, 4])
        self.dimension = self.model_config.get('dimension', 3)
        self.embedder_name = self.model_config.get('embedder', 'graph_spice')
        self.embedder = cluster_model_construct(
            self.model_config['embedder_cfg'], self.embedder_name)
        self.node_dim = self.model_config.get('node_dim', 16)

        self.kernel_cfg = self.model_config['kernel_cfg']
        self.kernel_fn = gs_kernel_construct(self.kernel_cfg)

        constructor_cfg = self.model_config['constructor_cfg']

        # Cluster Graph Manager
        self.gs_manager = ClusterGraphConstructor(constructor_cfg)
        self.gs_manager.training = self.training


    def filter_class(self, input):
        '''
        Filter classes according to segmentation label. 
        '''
        point_cloud, label = input
        mask = ~np.isin(label[:, -1].detach().cpu().numpy(), self.skip_classes)
        x = [point_cloud[mask], label[mask]]
        return x


    def forward(self, input):
        '''
        
        '''
        point_cloud, labels = self.filter_class(input)
        res = self.embedder([point_cloud])

        coordinates = point_cloud[:, :3]
        batch_indices = point_cloud[:, 3].int()
        res['coordinates'] = [coordinates]
        res['batch_indices'] = [batch_indices]
        graph = self.gs_manager(res, 
                                self.kernel_fn, 
                                labels)
        res['graph'] = [graph]
        res['graph_info'] = [self.gs_manager.info]
        return res


class GraphSPICEGNN(GraphSPICE):

    def __init__(self, cfg, name='graph_spice_gnn'):
        super(GraphSPICEGNN, self).__init__(cfg)

        self.gnn_cfg =self.model_config['gnn_cfg']
        in_channels = self.gnn_cfg['in_channels']
        gnn_kwargs = self.gnn_cfg['kwargs']
        self.gnn = torch_geometric.nn.DNAConv(channels=in_channels, 
                                              **gnn_kwargs)
    
    def forward(self, input):
        point_cloud, labels = self.filter_class(input)
        res = self.embedder([point_cloud])
        coordinates = point_cloud[:, :3]
        batch_indices = point_cloud[:, 3].int()
        res['coordinates'] = [coordinates]
        res['batch_indices'] = [batch_indices]
        # Run GNN
        self.gs_manager.initialize_graph(res, labels)
        graph = self.gs_manager.graph_batch
        x = graph.x.view(-1, 1, self.node_dim)
        edge_index = graph.edge_index
        edge_weight = get_edge_weight(
            res['spatial_embeddings'][0],
            res['feature_embeddings'][0],
            res['covariance'][0],
            edge_index,
            occ=res['occupancy'][0].squeeze())
        nodes = self.gnn(x=x, edge_index=edge_index, edge_weight=edge_weight)
        self.gs_manager.graph_batch.add_node_features(nodes, name='x')

        # Run GNN to get transformed node features
        self.gs_manager._set_edge_attributes(self.kernel_fn)
        res['graph'] = [graph]
        res['graph_info'] = [self.gs_manager.info]

        return res
        # graph = self.gs_manager(res, 
        #                         self.kernel_fn, 
        #                         labels)
        

class GraphSPICELoss(nn.Module):

    def __init__(self, cfg, name='spice_loss'):
        super(GraphSPICELoss, self).__init__()
        self.loss_config = cfg[name]
        print('--------------------GraphSPICELoss---------------------')
        pprint(self.loss_config)
        self.loss_name = self.loss_config['name']
        self.skip_classes = self.loss_config.get('skip_classes', [2, 3, 4])
        self.eval_mode = self.loss_config['eval']
        self.loss_fn = spice_loss_construct(self.loss_name)(self.loss_config)

        constructor_cfg = self.loss_config['constructor_cfg']
        self.gs_manager = ClusterGraphConstructor(constructor_cfg)
        self.gs_manager.training = ~self.eval_mode
        # print("LOSS FN = ", self.loss_fn)

    def filter_class(self, segment_label, cluster_label):
        '''
        Filter classes according to segmentation label. 
        '''
        mask = ~np.isin(segment_label[0][:, -1].cpu().numpy(), self.skip_classes)
        slabel = [segment_label[0][mask]]
        clabel = [cluster_label[0][mask]]
        return slabel, clabel


    def forward(self, result, segment_label, cluster_label):
        '''

        '''
        slabel, clabel = self.filter_class(segment_label, cluster_label)

        graph = result['graph'][0]
        graph_info = result['graph_info'][0]
        self.gs_manager.replace_state(graph, graph_info)
        result['edge_score'] = [graph.edge_attr]
        result['edge_index'] = [graph.edge_index]
        if not self.eval_mode:
            result['edge_truth'] = [graph.edge_truth]

        res = self.loss_fn(result, slabel, clabel)

        # Evaluate Graph with respect to cluster_label
        # with torch.no_grad():
        #     self.gs_manager.fit_predict()
        #     self.gs_manager.evaluate_nodes(clabel[0], [ARI])

        # res['true_acc'] = self.gs_manager.info['ARI'].mean()
        return res
