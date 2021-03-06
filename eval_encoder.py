#!/usr/bin/python3
#
# Copyright 2017 Giovanni Campagna <gcampagn@cs.stanford.edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>. 
'''
Created on Mar 29, 2017

@author: gcampagn
'''

import os
import sys
import numpy as np
import tensorflow as tf
import csv

import matplotlib
matplotlib.use('GTK3Cairo')
import matplotlib.pyplot as plt

from collections import OrderedDict
from tensorflow.python.util import nest

from models import Config, create_model
from util.loader import unknown_tokens, load_data, vectorize
from util.general_utils import get_minibatches

def is_function(token):
    return token.startswith('tt:')

def run():
    if len(sys.argv) < 3:
        print("** Usage: python3 " + sys.argv[0] + " <<Model Directory>> <<Test Set>>")
        sys.exit(1)

    np.random.seed(42)
    model_dir = sys.argv[1]
    config = Config.load(['./default.conf', os.path.join(model_dir, 'model.conf')])
    model = create_model(config)

    test_data = load_data(sys.argv[2], config.dictionary, config.grammar, config.max_length)

    with tf.Graph().as_default():
        tf.set_random_seed(1234)
        model.build()
        loader = tf.train.Saver()

        inputs, input_lengths, parses, labels, label_lengths = test_data
        
        final_encoder_state = tf.concat(nest.flatten(model.final_encoder_state), axis=1)
        final_encoder_size = final_encoder_state.get_shape()[1]

        final_states = OrderedDict()
        with tf.Session() as sess:
            loader.restore(sess, os.path.join(model_dir, 'best'))

            # capture all the final encoder states
            for input_batch, input_length_batch, parse_batch, label_batch, label_length_batch in get_minibatches([inputs, input_lengths, parses, labels, label_lengths],
                                                                                                                 config.batch_size):
                feed_dict = model.create_feed_dict(input_batch, input_length_batch, parse_batch)
                state_array = sess.run(final_encoder_state, feed_dict=feed_dict)
                #print state_array.shape

                for state, input, input_length, label, length in zip(state_array, input_batch, input_length_batch, label_batch, label_length_batch):
                    label = label[:length]
                    program = ' '.join(config.grammar.tokens[x] for x in label)# if is_function(config.grammar.tokens[x]))
                    if not program in final_states:
                        final_states[program] = [(state, input[:input_length])]
                    else:
                        final_states[program].append((state, input[:input_length]))

        prog_array = [prog for prog in final_states] #if len(final_states[prog]) > 1]
        prog_index = dict()
        num_programs = len(prog_array)
        print('num programs', num_programs)
        centers = np.zeros((num_programs, final_encoder_size), dtype=np.float32)
        for i, program in enumerate(prog_array):
            prog_index[program] = i
            centers[i] = np.mean([x[0] for x in final_states[program]], axis=0)

        eval_data = []
        with open(sys.argv[3]) as fp:
            for line in fp:
                sentence, gold, predicted, _ = line.strip().split('\t')
                if gold == predicted:
                    continue
                gold += ' <<EOS>>'
                predicted += ' <<EOS>>'
                if gold in prog_index and predicted in prog_index:
                    sentence_vector, sentence_length = vectorize(sentence, config.dictionary, config.max_length)
                    gold_index = prog_index[gold]
                    gold_center = centers[gold_index]
                    predicted_index = prog_index[predicted]
                    predicted_center = centers[predicted_index]
                    eval_data.append((gold, predicted, gold_center, predicted_center, sentence_vector, sentence_length))
                    #print(np.linalg.norm(gold_center-predicted_center), gold, predicted, sentence, sep='\t')
                elif gold not in prog_index:
                    #print('no gold', gold, file=sys.stderr)
                    pass
                elif predicted not in prog_index:
                    #print('no predicted', file=sys.stderr)
                    pass

        with tf.Session() as sess:
            loader.restore(sess, os.path.join(model_dir, 'best'))

            def flip(list_of_tuples):
                inner_length = len(list_of_tuples[0])
                tuple_of_lists = [[x[i] for x in list_of_tuples] for i in range(inner_length)]
                return tuple_of_lists

            with open('./eval.tsv', 'w') as out:
                for gold_batch, predicted_batch, gold_center_batch, predicted_center_batch, input_batch, input_length_batch in get_minibatches(flip(eval_data), config.batch_size):
                    parse_batch = np.zeros((len(input_batch), 2*config.max_length-1), dtype=np.bool)
                    feed_dict = model.create_feed_dict(input_batch, input_length_batch, parse_batch)
                    state_array = sess.run(final_encoder_state, feed_dict=feed_dict)

                    assert len(state_array) == len(gold_batch)
                    for state, input, input_length, gold, predicted, gold_center, predicted_center in zip(state_array, input_batch, input_length_batch, gold_batch, predicted_batch, gold_center_batch, predicted_center_batch):
                        gold_predicted_dist = np.linalg.norm(gold_center-predicted_center)
                        sentence_gold_dist = np.linalg.norm(state-gold_center)
                        sentence_predicted_dist = np.linalg.norm(state-predicted_center)
                        sentence = ' '.join(config.reverse_dictionary[x] for x in input[:input_length])
                        print(gold_predicted_dist, sentence_gold_dist, sentence_predicted_dist, gold, predicted, sentence, sep='\t', file=out)
        print('written eval.tsv')

        num_good_sentences = np.zeros((num_programs,), dtype=np.int32)
        sum_good_distance = np.zeros((num_programs,), dtype=np.float32)
        num_bad_sentences = np.zeros((num_programs,), dtype=np.int32)
        sum_bad_distance = np.zeros((num_programs,), dtype=np.float32)
        for i, program in enumerate(prog_array):
            num_good_sentences[i] = len(final_states[program])

            for encoding, sentence in final_states[program]:
                dist = np.linalg.norm(encoding - centers[i])
                sum_good_distance[i] += dist

            # negative examples
            for negative in np.random.choice(prog_array, size=(10,), replace=False):
                if negative == program:
                    continue
                num_bad_sentences[i] += len(final_states[negative])
                for negative_enc, negative_sentence in final_states[negative]:
                    dist = np.linalg.norm(negative_enc - centers[i])
                    sum_bad_distance[i] += dist

        avg_good_distance = sum_good_distance / num_good_sentences
        avg_bad_distance = sum_bad_distance / num_bad_sentences

        with open('./encoded.csv', 'w') as fp:
            writer = csv.writer(fp)
            writer.writerows(zip(num_good_sentences, num_bad_sentences, avg_good_distance, avg_bad_distance, sum_good_distance, sum_bad_distance))

            
if __name__ == '__main__':
    run()

