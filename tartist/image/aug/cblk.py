# -*- coding:utf8 -*-
# File   : cblk.py
# Author : Jiayuan Mao
# Email  : maojiayuan@gmail.com
# Date   : 3/14/17
# 
# This file is part of TensorArtist.

from .. import imgproc
from . import shape as shape_augment
from . import photography as photography_augment


def fbaug(img, target_shape=(224, 224), full_shape=(256, 256), is_train=True):
    if is_train:
        img = shape_augment.random_size_crop(img, target_shape, area_range=0.08, aspect_ratio=[3/4, 4/3])
        img = photography_augment.color_augment_pack(img, brightness=0.4, contrast=0.4, saturation=0.4)
        img = photography_augment.lighting_augment(img, 0.1)
        img = shape_augment.horizontal_flip_augment(img, 0.5)
        img = imgproc.clip(img).astype('uint8')
        return img
    else:
        # 1. scale the image
        scale = max(full_shape[0] / img.shape[0], full_shape[1] / img.shape[1])
        img = imgproc.resize_scale(img, scale)

        # 2. center crop 224x244 patch from the image
        return imgproc.center_crop(img, target_shape)
