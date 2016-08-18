define([
        'jquery',
        'underscore',
        'backbone',
        'js-cookie'
    ],
    function ($,
              _,
              Backbone
    ) {
        'use strict';

        return Backbone.View.extend({

            initialize: function () {
                this.button = this.$el.find('.payment-button');
            },

            setSku: function (sku) {
                this.button.attr('href', '/basket/single-item/?sku=' + sku);
            }
        });
    });
