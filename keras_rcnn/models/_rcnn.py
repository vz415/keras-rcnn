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

        output_features = keras.layers.Conv2D(64, **options)(output_features)

        convolution_3x3 = keras.layers.Conv2D(64, **options)(output_features)

        output_deltas = keras.layers.Conv2D(9 * 4, (1, 1), activation="linear", kernel_initializer="zero", name="deltas")(convolution_3x3)

        output_scores = keras.layers.Conv2D(9 * 1, (1, 1), activation="sigmoid", kernel_initializer="uniform", name="scores")(convolution_3x3)

        target_anchors, target_proposal_bounding_boxes, target_proposal_categories = keras_rcnn.layers.AnchorTarget()([
            target_bounding_boxes,
            target_metadata,
            output_scores
        ])

        output_deltas, output_scores = keras_rcnn.layers.RPN()([target_proposal_bounding_boxes, target_proposal_categories, output_deltas, output_scores])

        output_proposal_bounding_boxes = keras_rcnn.layers.ObjectProposal()([target_anchors, target_metadata, output_deltas, output_scores])

        target_proposal_bounding_boxes, target_proposal_categories, output_proposal_bounding_boxes = keras_rcnn.layers.ProposalTarget()([target_bounding_boxes, target_categories, output_proposal_bounding_boxes])

        output_features = keras_rcnn.layers.RegionOfInterest((14, 14))([target_metadata, output_features, output_proposal_bounding_boxes])

        output_features = keras.layers.TimeDistributed(keras.layers.Flatten())(output_features)

        # Think this is the 'pooled' region proposals.
        output_features = keras.layers.TimeDistributed(keras.layers.Dense(256, activation="relu"))(output_features)

        # Bounding Boxes - Regression network - why call it 'output_deltas'?
        output_deltas = keras.layers.TimeDistributed(
            keras.layers.Dense(
                units=4 * n_categories,
                activation="linear",
                kernel_initializer="zero",
                name="deltas2"
            )
        )(output_features)

        # Categories - Classification network that classifies each pixel into the classes predicted by first CNN
        output_scores = keras.layers.TimeDistributed(
            keras.layers.Dense(
                units=1 * n_categories,
                activation="softmax",
                kernel_initializer="zero",
                name="scores2"
            )
        )(output_features)

        # Masks
        output_masks = keras.layers.TimeDistributed(
            keras.layers.Conv2D(
                filters=256,
                kernel_size=(3, 3),
                activation="relu",
                padding="same"
            )
        )(output_features)

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

        # Loss layer
        output_deltas, output_scores = keras_rcnn.layers.RCNN()([
            target_proposal_bounding_boxes,
            target_proposal_categories,
            output_deltas,
            output_scores
        ])

        # New - Loss layer
        output_masks = keras_rcnn.layers.MaskRCNN()([
            target_proposal_categories, # previously 'target_proposal'
            target_masks,
            output_masks
        ]) # Deleted 'output_deltas'

        output_bounding_boxes, output_categories = keras_rcnn.layers.ObjectDetection()([
            target_metadata,
            output_deltas,
            output_proposal_bounding_boxes,
            output_scores
        ])

        # New - Redundant with previous call...
        output_bounding_boxes, output_labels = keras_rcnn.layers.ObjectDetection()([
            output_proposals, output_deltas, output_scores, target_metadata])

        # New
        output = [output_bounding_boxes, output_labels, output_masks]

        outputs = [
            output_bounding_boxes,
            output_categories
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