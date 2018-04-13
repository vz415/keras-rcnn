# -*- coding: utf-8 -*-

import keras.backend
import keras.engine
import keras.layers
import numpy

import keras_rcnn.backend
import keras_rcnn.classifiers
import keras_rcnn.datasets.malaria
import keras_rcnn.layers
import keras_rcnn.preprocessing
import keras_rcnn.models.backbone


class RCNN(keras.models.Model):
    """
    A Region-based Convolutional Neural Network (RCNN)
    Parameters
    ----------
    input_shape : A shape tuple (integer) without the batch dimension.
        For example:
            `input_shape=(224, 224, 3)`
        specifies that the input are batches of $224 × 224$ RGB images.
        Likewise:
            `input_shape=(224, 224)`
        specifies that the input are batches of $224 × 224$ grayscale
        images.

    categories : An array-like with shape:
            $$(categories,)$$.
        For example:
            `categories=["circle", "square", "triangle"]`
        specifies that the detected objects belong to either the
        “circle,” “square,” or “triangle” category.

    anchor_aspect_ratios : An array-like with shape:
            $$(aspect_ratios,)$$
        used to generate anchors.
        For example:
            `aspect_ratios=[0.5, 1., 2.]`
        corresponds to 1:2, 1:1, and 2:1 respectively.

    anchor_base_size : Integer that specifies an anchor’s base area:
            $$base_area = base_size^{2}$$.

    anchor_scales : An array-like with shape:
            $$(scales,)$$
        used to generate anchors. A scale corresponds to:
            $$area_{scale}=\sqrt{\frac{area_{anchor}}{area_{base}}}$$.

    anchor_stride : A positive integer

    backbone :

    dense_units : A positive integer that specifies the dimensionality of
        the fully-connected layer.
        The fully-connected layer is the layer that precedes the
        fully-connected layers for the classification, regression and
        segmentation target functions.
        Increasing the number of dense units will increase the
        expressiveness of the network and consequently the ability to
        correctly learn the target functions, but it’ll substantially
        increase the number of learnable parameters and memory needed by
        the model.

    mask_shape : A shape tuple (integer).

    maximum_proposals : A positive integer that specifies the maximum
        number of object proposals returned from the model.
        The model always return an array-like with shape:
            $$(maximum_proposals, 4)$$
        regardless of the number of object proposals returned after
        non-maximum suppression is performed. If the number of object
        proposals returned from non-maximum suppression is less than the
        number of objects specified by the `maximum_proposals` parameter,
        the model will return bounding boxes with the value:
            `[0., 0., 0., 0.]`
        and scores with the value `[0.]`.

    minimum_size : A positive integer that specifies the maximum width
        or height for each object proposal.
    """
    def __init__(
            self,
            input_shape,
            categories,
            anchor_aspect_ratios=None,
            anchor_base_size=16,
            anchor_padding=1,
            anchor_scales=None,
            anchor_stride=16,
            backbone=None,
            dense_units=512,
            mask_shape=(28, 28),
            maximum_proposals=300,
            minimum_size=16
    ):

        # New
        if anchor_aspect_ratios is None:
            anchor_aspect_ratios = [0.5, 1.0, 2.0]

        if anchor_scales is None:
            anchor_scales = [4, 8, 16]

        # New
        self.mask_shape = mask_shape

        # New
        self.n_categories = len(categories) + 1

        k = len(anchor_aspect_ratios) * len(anchor_scales)

        target_bounding_boxes = keras.layers.Input(
            shape=(None, 4),
            name="target_bounding_boxes"
        )

        target_categories = keras.layers.Input(
            shape=(None, self.n_categories),
            name="target_categories"
        )

        target_image = keras.layers.Input(
            shape=input_shape,
            name="target_image"
        )

        target_masks = keras.layers.Input(
            shape=(None,) + mask_shape,
            name="target_masks"
        )

        target_metadata = keras.layers.Input(
            shape=(3,),
            name="target_metadata"
        )

        options = {
            "activation": "relu",
            "kernel_size": (3, 3),
            "padding": "same"
        }

        inputs = [
            target_bounding_boxes,
            target_categories,
            target_image,
            target_masks,
            target_metadata
        ]

        if backbone:
            output_features = backbone()(target_image)
        else:
            output_features = keras_rcnn.models.backbone.VGG16()(target_image)

        convolution_3x3 = keras.layers.Conv2D(
            filters=64,
            name="3x3",
            **options
        )(output_features)

        output_deltas = keras.layers.Conv2D(
            filters=k * 4,
            kernel_size=(1, 1),
            activation="linear",
            kernel_initializer="zero",
            name="deltas1"
        )(convolution_3x3)

        output_scores = keras.layers.Conv2D(
            filters=k * 1,
            kernel_size=(1, 1),
            activation="sigmoid",
            kernel_initializer="uniform",
            name="scores1"
        )(convolution_3x3)

        # Definitely check that AnchorTarget is same as in Master branch - Anchor should be initialized to new class...
        target_anchors, target_proposal_bounding_boxes, target_proposal_categories = keras_rcnn.layers.Anchor(
            padding=anchor_padding,
            aspect_ratios=anchor_aspect_ratios,
            base_size=anchor_base_size,
            scales=anchor_scales,
            stride=anchor_stride
        )([
            target_bounding_boxes,
            target_metadata,
            output_scores
        ])

        output_deltas, output_scores = keras_rcnn.layers.RPN()([
            target_proposal_bounding_boxes,
            target_proposal_categories,
            output_deltas,
            output_scores
        ])

        # Check if this is the same as master branch
        output_proposal_bounding_boxes = keras_rcnn.layers.ObjectProposal(
            maximum_proposals=maximum_proposals,
            minimum_size=minimum_size
        )([
            target_anchors,
            target_metadata,
            output_deltas,
            output_scores
        ])

        target_proposal_bounding_boxes, target_proposal_categories, output_proposal_bounding_boxes = keras_rcnn.layers.ProposalTarget()([
            target_bounding_boxes,
            target_categories,
            output_proposal_bounding_boxes
        ])

        output_features_pooled = keras_rcnn.layers.RegionOfInterest((14, 14))([
            target_metadata,
            output_features,
            output_proposal_bounding_boxes
        ])

        output_features = keras.layers.TimeDistributed(
            keras.layers.Flatten()
        )(output_features_pooled)

        output_features = keras.layers.TimeDistributed(
            keras.layers.Dense(
                dense_units,
                activation="relu",
                name='fc1')
        )(output_features)

        # Bounding Boxes - Regression network - why call it 'output_deltas'?
        output_deltas = keras.layers.TimeDistributed(
            keras.layers.Dense(
                units=4 * self.n_categories,
                activation="linear",
                kernel_initializer="zero",
                name="deltas2"
            )
        )(output_features)

        # Categories - Classification network that classifies each pixel into the classes predicted by first CNN
        output_scores = keras.layers.TimeDistributed(
            keras.layers.Dense(
                units=1 * self.n_categories,
                activation="softmax",
                kernel_initializer="zero",
                name="scores2"
            )
        )(output_features)

        # Masks branch
        output_masks = keras.layers.TimeDistributed(
            keras.layers.Conv2D(
                filters=256,
                kernel_size=(3, 3),
                activation="relu",
                padding="same"
            )
        )(output_features_pooled)

        output_masks = keras.layers.TimeDistributed(
            keras.layers.Conv2DTranspose(
                activation="relu",
                filters=256,
                kernel_size=(2, 2),
                strides=2
            )
        )(output_masks)

        output_masks = keras.layers.TimeDistributed(
            keras.layers.Conv2D(
                activation="sigmoid",
                filters=self.n_categories,
                kernel_size=(1, 1),
                strides=1
            )
        )(output_masks)
        # End Masks ---------------------------------

        # Losses
        output_deltas, output_scores = keras_rcnn.layers.RCNN()([
            target_proposal_bounding_boxes,
            target_proposal_categories,
            output_deltas,
            output_scores
        ])

        # New - Mask Loss layer
        output_masks = keras_rcnn.layers.MaskRCNN()([
            target_proposal_categories, # previously 'target_proposal'
            target_masks,
            output_masks
        ]) # Deleted 'output_deltas'

        # bbox loss stuff?
        output_bounding_boxes, output_categories = keras_rcnn.layers.ObjectDetection()([
            target_metadata,
            output_deltas,
            output_proposal_bounding_boxes,
            output_scores
        ])

        # New
        outputs = [
            output_bounding_boxes,
            output_categories,
            output_masks
        ]

        super(RCNN, self).__init__(inputs, outputs)

    def compile(self, optimizer, **kwargs):
        super(RCNN, self).compile(optimizer, None)

    # New
    def predict(self, x, batch_size=None, verbose=0, steps=None):
        target_bounding_boxes = numpy.zeros((x.shape[0], 1, 4))

        target_categories = numpy.zeros((x.shape[0], 1, self.n_categories))

        target_mask = numpy.zeros((1, 1, *self.mask_shape))

        target_metadata = numpy.array([[x.shape[1], x.shape[2], 1.0]])

        x = [
            target_bounding_boxes,
            target_categories,
            x,
            target_mask,
            target_metadata
        ]

        return super(RCNN, self).predict(x, batch_size, verbose, steps)