from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
import pytest
from spine.models import factories
import numpy as np
import torch
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''


@pytest.mark.parametrize("num_voxels_low", [20])
@pytest.mark.parametrize("num_voxels_high", [100])
def test_model_forward(config_simple, xfail_models, N, num_voxels_low, num_voxels_high):
    """
    Test whether a model can be trained.
    Using only numpy input arrays, should also test with parsers running.

    Parameters
    ----------
    config: dict
        Generated by a fixture above, dummy config to allow networks to run.
        It is mostly empty, we rely on networks default config.
    N: int
        Spatial size
    num_voxels_low: int, optional
        Lower boundary for generating (random) number of voxels.
    num_voxels_high: int, optional
        Upper boundary for generating (random) number of voxels.
    """
    if config_simple['model']['name'] in xfail_models:
        pytest.xfail("%s is expected to fail at the moment." % config_simple['model']['name'])

    config = config_simple
    model, criterion = factories.construct(config['model']['name'])
    net = model(config['model']['modules'])
    loss = criterion(config['model']['modules'])

    if not hasattr(net, "INPUT_SCHEMA"):
        pytest.skip('No test defined for network of %s' % config['model']['name'])

    net_input, voxels = generate_data(N, net.INPUT_SCHEMA,
                                      num_voxels_low=num_voxels_low,
                                      num_voxels_high=num_voxels_high)
    output = net.forward(net_input)

    if not hasattr(loss, "INPUT_SCHEMA"):
        pytest.skip('No test defined for criterion of %s' % config['model']['name'])


    loss_input = generate_data(N, loss.INPUT_SCHEMA,
                                 num_voxels_low=num_voxels_low,
                                 num_voxels_high=num_voxels_high,
                                 voxels=voxels,
                                 loss=True)[0]
    res = loss.forward(output, *loss_input)

    res['loss'].backward()


def generate_data(N, input_schema, num_voxels_low=20, num_voxels_high=100,
                  voxels=None, loss=False):
    """
    Generates dummy data for the network and loss input to be used in tests.

    Arguments
    ---------
    N: int
        Spatial size
    input_schema: list
        Description of input data
    num_voxels_low: int, optional
        Lower boundary for generating (random) number of voxels.
    num_voxels_high: int, optional
        Upper boundary for generating (random) number of voxels.
    voxels: np.array, optional
        Allows to reuse the same voxels across different calls to generate_data
        specifically between network forward and loss forward.
    loss: bool, optional
        If this input is going to be used for the loss forward, wrap it a bit
        differently (because of DataParallel) than for network forward.
    """
    net_input = ()
    num_voxels = np.random.randint(low=num_voxels_low, high=num_voxels_high)
    original_voxels = voxels
    for schema in input_schema:
        obj = None
        shapes = schema[2] #parsers[schema[0]]
        types = schema[1]
        if isinstance(shapes, list):
            out = []
            if original_voxels is None:
                original_voxels = np.random.random((num_voxels, shapes[0][0])) * N

            voxels = original_voxels
            values = []
            for t in types:
                values.append(np.random.random((voxels.shape[0], shapes[0][1])).astype(t))
            out.append(np.concatenate([voxels, np.zeros((voxels.shape[0], 1))] + values, axis=1))

            for shape in shapes[1:]:
                voxels = np.floor(voxels/float(2))
                voxels, indices = np.unique(voxels, axis=0, return_index=True)
                for i in range(len(values)):
                    values[i] = values[i][indices]
                out.append(np.concatenate([voxels, np.zeros((voxels.shape[0], 1))] + values, axis=1))
            obj = out
            net_input += ([torch.tensor(x) for x in obj],) if not loss else ([[torch.tensor(x) for x in obj]],)
        elif isinstance(shapes, tuple):
            if original_voxels is None:
                original_voxels = np.random.random((num_voxels, shapes[0])) * N

            voxels = original_voxels
            values = []
            assert len(types) == shapes[1]
            for t in types:
                values.append(np.random.random((voxels.shape[0], 1)).astype(t))
            obj = np.concatenate([voxels, np.zeros((voxels.shape[0], 1))] + values, axis=1)
            net_input += (torch.tensor(obj),) if not loss else ([torch.tensor(obj)],)

    return net_input, original_voxels
