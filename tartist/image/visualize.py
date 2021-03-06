# -*- coding:utf8 -*-
# File   : visualize.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 3/23/17
# 
# This file is part of TensorArtist.

import io as _io
import numpy as np
from ._backend import cv2, opencv_only

try:
    import matplotlib.pyplot as plt
except ImportError:
    pass


__all__ = ['image_grid']


def image_grid(all_images, grid_desc):
    """
    Create a image grid given the description. The description is a list of axis desc, of format: %d[h|v].
    If the first number n is a positive number, every n images will be concatenated horizontally or vertically.
    We allow exactly one axis desc to be only [h|v], meaning the number of images of that axis will be automatically
    inferred. See examples/generative-model/data_provide_gan_mnist/main_demo_infogan for detail.
    :param all_images: A list of images. Should be np.ndarray of shape (h, w, c).
    :param grid_desc: The grid description.
    :return: A single big image created.
    """

    axes_info = []
    auto_infer_dim = len(all_images)
    for d in grid_desc:
        if d == 'h' or d == 'v':
            axes_info.append([None, d])
        else:
            assert d.endswith('h') or d.endswith('v'), d
            length, axis = int(d[:-1]), d[-1]
            assert auto_infer_dim % length == 0, 'Length of all_images should be divided by axes_info, ' \
                                                 'got {} and {}'.format(len(all_images), grid_desc)
            axes_info.append((length, axis))
            auto_infer_dim //= length

    for i, info in enumerate(axes_info):
        if info[0] is None:
            axes_info[i] = (auto_infer_dim, info[1])

    def stack(i, sequence):
        axis = axes_info[i][1]
        if len(sequence) == 1:
            return sequence[0]
        if axis == 'h':
            return np.hstack(sequence)
        return np.vstack(sequence)

    n = len(axes_info)

    def recursive_concat(i, sequence):
        if i == n - 1:
            return stack(i, sequence)

        nr_parts = axes_info[i][0]
        length = len(sequence) // nr_parts
        parts = []
        for j in range(nr_parts):
            part = recursive_concat(i+1, sequence[j*length:(j+1)*length])
            parts.append(part)
        return stack(i, parts)

    return recursive_concat(0, all_images)


@opencv_only
def pyplot2img(plt):
    """Convert a pyplot instance to image"""

    buf = _io.BytesIO()
    plt.axis('off')
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
    buf.seek(0)
    rawbuf = np.frombuffer(buf.getvalue(), dtype='uint8')
    im = cv2.imdecode(rawbuf, cv2.IMREAD_COLOR)
    buf.close()
    return im
