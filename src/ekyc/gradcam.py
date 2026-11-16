"""Grad-CAM heat maps for the EfficientNet forgery detector, and the pointing-game check.

Grad-CAM (Selvaraju et al., 2017) shows which image regions raised the model's "forged" score:
  1. take the last convolutional feature maps A (16 x 16 x 1280 for a 512 px input);
  2. compute the gradient of the forged score (before the sigmoid) with respect to A;
  3. average each channel's gradient over the 16 x 16 positions -> one weight per channel;
  4. heat = ReLU(sum over channels of weight x A), scaled to 0-1 and enlarged to the input size.
With a global-average-pooling + dense head (our model), step 2-3 has an exact closed form: the
logit is sum_k w_k * mean(A_k) + b, so d logit / d A_k(i, j) = w_k / (16 * 16) at every position,
and the channel weights are simply the dense weights divided by 256 (Grad-CAM = the classic Class
Activation Map). We use this closed form instead of tf.GradientTape: it gives identical maps
(checked in tests/test_forgery.py) and avoids back-propagating through the convolutions, which
aborts the process on the Apple Metal GPU plugin (conv2d_backprop_filter crash).

Pointing game: a heat map "points" at the right place if its single hottest pixel lies inside the
annotated box of the altered field.
"""

from __future__ import annotations

import keras
import numpy as np
import tensorflow as tf

from ekyc.tfdata import pad_geometry


def gradcam_parts(model: keras.Model, backbone_name: str = "efficientnetb0",
                  conv_layer: str = "top_activation") -> tuple[keras.Model, keras.layers.Layer]:
    """Split the trained detector into (feature model, output layer).
    The feature model maps an image to [last conv feature maps, pooled 1280 features]."""
    backbone = model.get_layer(backbone_name)
    feature_model = keras.Model(backbone.inputs, [backbone.get_layer(conv_layer).output, backbone.output])
    return feature_model, model.get_layer("forged")


def channel_weights(output_layer: keras.layers.Layer, feature_maps: tf.Tensor) -> tf.Tensor:
    """Grad-CAM channel weights alpha_k = mean over positions of d logit / d A_k, in closed form:
    w_k / (height * width) of the feature maps (see module docstring). Shape (channels,)."""
    height, width = feature_maps.shape[1], feature_maps.shape[2]
    return output_layer.kernel[:, 0] / (height * width)


def gradcam(feature_model: keras.Model, output_layer: keras.layers.Layer, images: tf.Tensor) -> np.ndarray:
    """Heat maps (batch, H, W) in 0-1 for a batch of input images (batch, H, W, 3), raw 0-255.
    The score explained is the forged logit (before the sigmoid)."""
    feature_maps, _ = feature_model(images, training=False)  # (batch, 16, 16, 1280)
    weights = channel_weights(output_layer, feature_maps)  # (1280,)
    heat = tf.nn.relu(tf.einsum("bhwc,c->bhw", feature_maps, weights))
    heat = heat / (tf.reduce_max(heat, axis=(1, 2), keepdims=True) + 1e-8)
    size = images.shape[1:3]
    return tf.image.resize(heat[..., None], size, method="bilinear")[..., 0].numpy()


def box_to_input(box_xywh, orig_size: tuple[int, int], cache_size: tuple[int, int],
                 input_size: int) -> tuple[float, float, float, float]:
    """Map an annotation box from ORIGINAL template pixels to model-input pixels.

    original -> cache: scale by cache_width / original_width (the cache keeps the aspect ratio);
    cache -> input:    resize_with_pad scale and centring offset (see tfdata.pad_geometry).
    Returns (x, y, w, h) in input pixels.
    """
    x, y, w, h = box_xywh
    to_cache = cache_size[0] / orig_size[0]
    scale, off_x, off_y = pad_geometry(cache_size[0], cache_size[1], input_size)
    s = to_cache * scale
    return x * s + off_x, y * s + off_y, w * s, h * s


def peak_location(heat: np.ndarray) -> tuple[int, int]:
    """(x, y) of the hottest pixel of one heat map."""
    row, col = np.unravel_index(np.argmax(heat), heat.shape)
    return int(col), int(row)


def point_in_box(point: tuple[float, float], box_xywh) -> bool:
    x, y = point
    bx, by, bw, bh = box_xywh
    return bx <= x <= bx + bw and by <= y <= by + bh
