
import tensorflow as tf
import numpy as np

from orderedset import OrderedSet
from collections import OrderedDict

import sys

from .abstract import AbstractGrammar

ENTITIES = ['USERNAME', 'HASHTAG',
            'QUOTED_STRING', 'NUMBER',
            'PHONE_NUMBER', 'EMAIL_ADDRESS', 'URL',
            'DATE', 'TIME', 'DURATION',
            'LOCATION']

BEGIN_TOKENS = ['bookkeeping', 'rule']
BOOKKEEPING_TOKENS = ['special', 'answer', 'command', 'help', 'generic']
SPECIAL_TOKENS = ['tt:root.special.yes', 'tt:root.special.no', 'tt:root.special.nevermind',
                  'tt:root.special.makerule', 'tt:root.special.failed']

OPERATORS = ['is', 'contains', '>', '<', 'has']
VALUES = ['true', 'false', 'absolute', 'rel_home', 'rel_work', 'rel_current_location', '1', '0']
TYPES = {
    'Location': (['is'], ['LOCATION', 'rel_current_location', 'rel_work', 'rel_home']),
    'Boolean':  (['is'], ['true', 'false']),
    'Bool': (['is'], ['true', 'false']),
    'String': (['is', 'contains'], ['QUOTED_STRING']),
    'Date': (['is'], ['DATE']),
    'Time': (['is'], ['TIME']),
    'Number': (['is', '<', '>'], ['NUMBER', '1', '0']),
    'Entity(tt:contact)': (['is'], ['USERNAME', 'QUOTED_STRING']),
    'Entity(tt:username)': (['is'], ['USERNAME', 'QUOTED_STRING']),
    'Entity(tt:hashtag)': (['is'], ['HASHTAG', 'QUOTED_STRING']),
    'Entity(tt:phone_number)': (['is'], ['USERNAME', 'PHONE_NUMBER', 'QUOTED_STRING']),
    'Entity(tt:email_address)': (['is'], ['USERNAME', 'EMAIL_ADDRESS', 'QUOTED_STRING']),
    'Entity(tt:url)': (['is'], ['URL', 'QUOTED_STRING']),
    'Entity(tt:picture)': (['is'], [])
}
TYPE_RENAMES = {
    'Username': 'Entity(tt:username)',
    'Hashtag': 'Entity(tt:hashtag)',
    'PhoneNumber': 'Entity(tt:phone_number)',
    'EmailAddress': 'Entity(tt:email_address)',
    'URL': 'Entity(tt:url)',
    'Picture': 'Entity(tt:picture)'
}

UNITS = dict(C=["C", "F"],
             ms=["ms", "s", "min", "h", "day", "week", "month", "year"],
             m=["m", "km", "mm", "cm", "mi", "in", "ft"],
             mps=["mps", "kmph", "mph"],
             kg=["kg", "g", "lb", "oz"],
             kcal=["kcal", "kJ"],
             bpm=["bpm"],
             byte=["byte", "KB", "KiB", "MB", "MiB", "GB", "GiB", "TB", "TiB"])

MAX_ARG_VALUES = 8

# first token is "special", "command" or "answer"
# "specials": yes, no, makerule...
# single token answers: "home" "work" "true" "false" etc.
# "help" + "generic"
# "help" + device
# two token answers: NUMBER_i + unit
# three tokens + EOS = 4
MAX_SPECIAL_LENGTH = 4
MAX_PRIMITIVE_LENGTH = 30

class ThingtalkGrammar(AbstractGrammar):
    def __init__(self, filename):
        super().__init__()
        
        triggers = OrderedDict()
        queries = OrderedDict()
        actions = OrderedDict()
        functions = dict(trigger=triggers, query=queries, action=actions)
        self.functions = functions
        self.entities = OrderedSet()
        devices = []
        trigger_or_query_params = set()

        enum_types = OrderedDict()

        # Token order:
        # first the padding, go and end of sentence
        # then the begin tokens
        # then triggers - queries - actions
        # in this order
        # then parameters names
        # then operators
        # then values
        # then entity tokens
        #
        # This order is important as it affects the 3-part aligner
        # algorithm

        tokens = ['<<PAD>>', '<<EOS>>', '<<GO>>']
        self.num_control_tokens = 3
        tokens += BEGIN_TOKENS
        self.num_begin_tokens = len(BEGIN_TOKENS)
        
        # add the special functions
        functions['trigger']['tt:$builtin.now'] = []
        functions['query']['tt:$builtin.noop'] = []
        functions['action']['tt:$builtin.notify'] = []
        
        param_tokens = OrderedSet()
        param_tokens.add('tt-param:$event')
        trigger_or_query_params.add('tt-param:$event')
        
        with open(filename, 'r') as fp:
            for line in fp.readlines():
                line = line.strip().split()
                function_type = line[0]
                function = line[1]
                if function_type == 'device':
                    devices.append(function)
                    continue
                if function_type == 'entity':
                    self.entities.add(function)
                    continue

                parameters = line[2:]
                paramlist = []
                functions[function_type][function] = paramlist
                
                for i in range(len(parameters)//2):
                    param = parameters[2*i]
                    type = parameters[2*i+1]
                    
                    paramlist.append((param, type))
                    param_tokens.add('tt-param:' + param)
                    if function_type != 'action':
                        trigger_or_query_params.add('tt-param:' + param)
                    
                    if type.startswith('Array('):
                        elementtype = type[len('Array('):-1]
                    else:
                        elementtype = type
                    if elementtype.startswith('Enum('):
                        enums = elementtype[len('Enum('):-1].split(',')
                        if not elementtype in enum_types:
                            enum_types[elementtype] = enums
        
        for function_type in ('trigger', 'query', 'action'):
            for function in functions[function_type]:
                tokens.append(function)
        self.num_functions = len(tokens) - self.num_control_tokens - self.num_begin_tokens
        
        tokens += param_tokens
        self.num_params = len(param_tokens)

        tokens += OPERATORS
        tokens += VALUES
        tokens += SPECIAL_TOKENS
        tokens += BOOKKEEPING_TOKENS     
        tokens += devices
        
        enumtokenset = set()
        for enum_type in enum_types.values():
            for enum in enum_type:
                if enum in enumtokenset:
                    continue
                enumtokenset.add(enum)
                tokens.append(enum)
        
        for unitlist in UNITS.values():
            tokens += unitlist
        
        for i in range(MAX_ARG_VALUES):
            for entity in ENTITIES:
                tokens.append(entity + "_" + str(i))
        for generic_entity in self.entities:
            for i in range(MAX_ARG_VALUES):
                tokens.append('GENERIC_ENTITY_' + generic_entity + "_" + str(i))
        
        print('num functions', self.num_functions)
        print('num triggers', len(self.functions['trigger']))
        print('num queries', len(self.functions['query']))
        print('num actions', len(self.functions['action']))
        print('num params', self.num_params)
        first_value_token = self.num_functions + self.num_begin_tokens + self.num_control_tokens
        print('num value tokens', len(tokens) - first_value_token)
        
        self.tokens = tokens
        self.dictionary = dict()
        for i, token in enumerate(self.tokens):
            self.dictionary[token] = i
        
        # build a DFA that will parse the thingtalk-ish code

        states = []
        transitions = []
        state_names = []
        
        def to_ids(tokens, words):
            return list([words[x] for x in tokens])

        def add_allowed_tokens(state, tokens):
            state[to_ids(tokens, self.dictionary)] = 1
        
        def new_state(name):
            state = np.zeros((self.output_size,))
            states.append(state)
            state_names.append(name)
            return len(states)-1
        
        # start with one of the begin tokens
        self.start_state = new_state('start')
        
        # in the before end state we just wait for EOS
        self.before_end_state = new_state('before_end')
        
        # in the end state we are done
        self.end_state = new_state('end')
        transitions.append((self.before_end_state, self.end_state, '<<EOS>>'))
        transitions.append((self.end_state, self.end_state, '<<PAD>>'))
        
        # bookkeeping
        bookkeeping_id = new_state('bookkeeping')
        transitions.append((self.start_state, bookkeeping_id, 'bookkeeping'))
        transitions.append((bookkeeping_id, self.end_state, '<<EOS>>'))
        self.bookeeping_state_id = bookkeeping_id
        
        # special
        special_id = new_state('special')
        transitions.append((bookkeeping_id, special_id, 'special'))
        for t in SPECIAL_TOKENS:
            transitions.append((special_id, self.before_end_state, t))
            
        # command
        command_id = new_state('command')
        transitions.append((bookkeeping_id, command_id, 'command'))
        # help/configure/discover command
        help_id = new_state('device_or_generic')
        transitions.append((command_id, help_id, 'help'))
        transitions.append((help_id, self.before_end_state, 'generic'))
        for d in devices:
            transitions.append((help_id, self.before_end_state, d))
        
        # answers
        answer_id = new_state('answer')
        transitions.append((bookkeeping_id, answer_id, 'answer'))
        for v in VALUES:
            if v != '0' and v != '1':
                transitions.append((answer_id, self.before_end_state, v))
        for v in ENTITIES:
            if v != 'NUMBER':
                for i in range(MAX_ARG_VALUES):
                    transitions.append((answer_id, self.before_end_state, v + '_' + str(i)))
        before_unit = new_state('answer_before_unit')
        for i in range(MAX_ARG_VALUES):
            transitions.append((answer_id, before_unit, 'NUMBER_' + str(i)))
        transitions.append((answer_id, before_unit, '0'))
        transitions.append((answer_id, before_unit, '1'))
        transitions.append((before_unit, self.end_state, '<<EOS>>'))
        for base_unit in UNITS:
            for unit in UNITS[base_unit]:
                transitions.append((before_unit, self.before_end_state, unit))
        
        def do_invocation(invocation_name, params, for_action=False):
            state_id = new_state(invocation_name)
            
            # allow one USERNAME_ parameter to follow the invocation immediately
            for i in range(MAX_ARG_VALUES):
                transitions.append((state_id, state_id, 'USERNAME_' + str(i)))
            
            # go to each parameter
            for param_name, param_type in params:
                if param_type in ('Any'):
                    continue
                elementtype = param_type
                is_array = False
                is_measure = False
                if param_type.startswith('Array('):
                    is_array = True
                    elementtype = param_type[len('Array('):-1]
                if elementtype in TYPE_RENAMES:
                    elementtype = TYPE_RENAMES[elementtype]
                if elementtype.startswith('Measure('):
                    is_measure = True
                    operators = ['is', '<', '>']
                    base_unit = elementtype[len('Measure('):-1]
                    values = UNITS[base_unit]
                elif elementtype.startswith('Enum('):
                    operators = ['is']
                    values = enum_types[elementtype]
                elif elementtype == 'Entity(tt:device)':
                    operators = ['is']
                    values = devices
                elif elementtype in TYPES:
                    operators, values = TYPES[elementtype]
                elif elementtype.startswith('Entity('):
                    operators = ['is']
                    values = ['GENERIC_ENTITY_' + elementtype[len('Entity('):-1], 'QUOTED_STRING']
                else:
                    operators, values = TYPES[elementtype]
                if is_array:
                    if for_action:
                        continue
                    else:
                        operators = ['has']
                elif for_action:
                    operators = ['is']
                
                before_op = new_state(invocation_name + '_tt-param:.' + param_name)
                transitions.append((state_id, before_op, 'tt-param:' + param_name))
                before_value = new_state(invocation_name + '_tt-param:' + param_name + ':value')

                for op in operators:
                    transitions.append((before_op, before_value, op))
                if is_measure:
                    before_unit = new_state(invocation_name + '_tt-param:' + param_name + ':unit')
                    for i in range(MAX_ARG_VALUES):
                        transitions.append((before_value, before_unit, '0'))
                        transitions.append((before_value, before_unit, '1'))
                        transitions.append((before_value, before_unit, 'NUMBER_' + str(i)))
                    for unit in values:
                        transitions.append((before_unit, state_id, unit))
                else:
                    for v in values:
                        if v[0].isupper():
                            for i in range(MAX_ARG_VALUES):
                                transitions.append((before_value, state_id, v + '_' + str(i)))
                        else:
                            transitions.append((before_value, state_id, v))
                if is_measure and base_unit == 'ms':
                    for i in range(MAX_ARG_VALUES):
                        transitions.append((before_value, state_id, 'DURATION_' + str(i)))
                for v in trigger_or_query_params:
                    transitions.append((before_value, state_id, v))
                    
            return state_id
        
        # rules
        rule_id = new_state('rule')
        transitions.append((self.start_state, rule_id, 'rule'))
        trigger_ids = []
        query_ids = []
        
        for trigger_name, params in triggers.items():
            state_id = do_invocation(trigger_name, params, for_action=False)
            transitions.append((rule_id, state_id, trigger_name))
            trigger_ids.append(state_id)
        for query_name, params in queries.items():
            state_id = do_invocation(query_name, params, for_action=False)
            for trigger_id in trigger_ids:
                transitions.append((trigger_id, state_id, query_name))
            query_ids.append(state_id)
        for action_name, params in actions.items():
            state_id = do_invocation(action_name, params, for_action=True)
            for query_id in query_ids:
                transitions.append((query_id, state_id, action_name))
            transitions.append((state_id, self.end_state, '<<EOS>>'))
            
        # do a second copy of the transition matrix for split sequences
        self.function_states = np.zeros((self.num_functions,), dtype=np.int32)
        self.function_states.fill(-1)
        for part in ('trigger', 'query', 'action'):
            for function_name, params in self.functions[part].items():
                token = self.dictionary[function_name] - self.num_control_tokens - self.num_begin_tokens
                state_id = do_invocation(function_name, params, for_action=(part == 'action'))
                transitions.append((state_id, self.end_state, '<<EOS>>'))
                self.function_states[token] = state_id
                

        # now build the actual DFA
        num_states = len(states)
        self.num_states = num_states
        print("num states", num_states)
        print("num tokens", self.output_size)
        self.transition_matrix = np.zeros((num_states, self.output_size), dtype=np.int32)
        self.transition_matrix.fill(-1)
        self.allowed_token_matrix = np.zeros((num_states, self.output_size), dtype=np.bool8)

        for from_state, to_state, token in transitions:
            token_id = self.dictionary[token]
            if self.transition_matrix[from_state, token_id] != -1 and \
                self.transition_matrix[from_state, token_id] != to_state:
                raise ValueError("Ambiguous transition around token " + token + " in state " + state_names[from_state])
            self.transition_matrix[from_state, token_id] = to_state
            self.allowed_token_matrix[from_state, token_id] = True

        if True:
            visited = set()
            def dfs(state):
                visited.add(state)
                any_out = False
                for next_state in self.transition_matrix[state]:
                    if next_state == -1:
                        continue
                    any_out = True
                    if next_state in visited:
                        continue
                    dfs(next_state)
                if not any_out:
                    raise ValueError('Reachable state %d (%s) has no outgoing states' % (state, state_names[state]))
            dfs(self.start_state)

        self.state_names = state_names

    def get_embeddings(self, use_types=False):
        if not use_types:
            return np.identity(self.output_size, np.float32)
        
        num_entity_tokens = (len(ENTITIES) + len(self.entities)) * MAX_ARG_VALUES
        num_other_tokens = len(self.tokens) - num_entity_tokens
        
        num_entities = len(ENTITIES) + len(self.entities)
        embed_size = num_other_tokens + num_entities + MAX_ARG_VALUES
        embedding = np.zeros((len(self.tokens), embed_size), dtype=np.float32)
        for token_id, token in enumerate(self.tokens):
            if '_' in token and token[0].isupper():
                continue
            embedding[token_id,token_id] = 1
        for i, entity in enumerate(ENTITIES):
            assert not np.any(embedding[:, num_other_tokens + i] > 0)
            for j in range(MAX_ARG_VALUES):
                token_id = self.dictionary[entity + '_' + str(j)]
                embedding[token_id, num_other_tokens + i] = 1
                embedding[token_id, num_other_tokens + num_entities + j] = 1
        for i, entity in enumerate(self.entities):
            assert not np.any(embedding[:, num_other_tokens + len(ENTITIES) + i] > 0)
            for j in range(MAX_ARG_VALUES):
                token_id = self.dictionary['GENERIC_ENTITY_' + entity + '_' + str(j)]
                embedding[token_id, num_other_tokens + len(ENTITIES) + i] = 1
                embedding[token_id, num_other_tokens + num_entities + j] = 1
        
        for i in range(len(embedding)):
            assert np.any(embedding[i] > 0)
        return embedding

    def dump_tokens(self):
        for token in self.tokens:
            print(token)

    def split_batch_in_parts(self, labels_batch):
        batch_size = len(labels_batch)
        top_batch = np.empty((batch_size,), dtype=np.int32)
        special_label_batch = np.zeros((batch_size, MAX_SPECIAL_LENGTH), dtype=np.int32)
        part_function_batches = dict()
        part_sequence_batches = dict()
        part_sequence_length_batches = dict()
        for part in ('trigger', 'query', 'action'):
            part_function_batches[part] = np.zeros((batch_size,), dtype=np.int32)
            part_sequence_batches[part] = np.zeros((batch_size, MAX_PRIMITIVE_LENGTH), dtype=np.int32)
            part_sequence_length_batches[part] = np.zeros((batch_size,), dtype=np.int32)
            
        rule_token = self.dictionary['rule']
        first_value_token = self.num_functions + self.num_begin_tokens + self.num_control_tokens
        for i, label in enumerate(labels_batch):
            top_batch[i] = label[0]
            if top_batch[i] != rule_token:
                special_label_batch[i] = label[1:1+MAX_SPECIAL_LENGTH]
                for part in ('trigger', 'query', 'action'):
                    if part == 'trigger':
                        function_offset = self.num_begin_tokens + self.num_control_tokens
                    elif part == 'query':
                        function_offset = self.num_begin_tokens + self.num_control_tokens + len(self.functions['trigger'])
                    else:
                        function_offset = self.num_begin_tokens + self.num_control_tokens + len(self.functions['trigger']) + len(self.functions['query'])
                    # add dummy values to the sequences to preserve the ability to compute
                    # losses and grammar constraints
                    part_function_batches[part][i] = function_offset
                    part_sequence_batches[part][i,0] = self.end
            else:
                special_label_batch[i,0] = self.end
                j = 1
                for part in ('trigger', 'query', 'action'):
                    if part == 'trigger':
                        function_offset = self.num_begin_tokens + self.num_control_tokens
                    elif part == 'query':
                        function_offset = self.num_begin_tokens + self.num_control_tokens + len(self.functions['trigger'])
                    else:
                        function_offset = self.num_begin_tokens + self.num_control_tokens + len(self.functions['trigger']) + len(self.functions['query'])
                    function_max = len(self.functions[part])
                    assert function_offset <= label[j] < function_offset+function_max, (function_offset, function_max, label[j], self.tokens[label[j]])
                    
                    part_function_batches[part][i] = label[j]
                    j += 1
                    start = j
                    while label[j] >= first_value_token:
                        j+= 1
                    end = j
                    assert end-start+1 < MAX_PRIMITIVE_LENGTH
                    part_sequence_batches[part][i,0:end-start] = label[start:end]
                    part_sequence_batches[part][i,end-start] = self.end
                    part_sequence_length_batches[part][i] = end-start+1
        return top_batch, special_label_batch, part_function_batches, part_sequence_batches, part_sequence_length_batches

    def vectorize_program(self, program, max_length=60):
        vector, length = super().vectorize_program(program, max_length)
        self.normalize_sequence(vector)
        return vector, length

    def parse(self, program):
        curr_state = self.start_state
        for token_id in program:
            next = self.transition_matrix[curr_state, token_id]
            if next == -1:
                raise ValueError("Unexpected token " + self.tokens[token_id] + " in " + (' '.join(self.tokens[x] for x in program)) + " (in state " + self.state_names[curr_state] + ")")
            #print("transition", self.state_names[curr_state], "->", self.state_names[next])
            curr_state = next

        if curr_state != self.end_state:
            raise ValueError("Premature end of program in " + (' '.join(self.tokens[x] for x in program)) + " (in state " + self.state_names[curr_state] + ")")
        #print(*(self.tokens[x] for x in program))

    def parse_all(self, fp):
        vectors = []
        for line in fp.readlines():
            try:
                program = line.strip().split()
                vector = self.vectorize_program(program)[0]
                self.parse(vector)
                vectors.append(vector)
            except ValueError as e:
                print(e)
        return np.array(vectors, dtype=np.int32)

    def get_function_init_state(self, function_tokens):
        next_state = tf.gather(self.function_states, function_tokens - (self.num_begin_tokens + self.num_control_tokens))
        assert2 = tf.Assert(tf.reduce_all(next_state >= 0), [function_tokens])
        with tf.control_dependencies([assert2]):
            return tf.identity(next_state)

    def get_init_state(self, batch_size):
        return tf.ones((batch_size,), dtype=tf.int32) * self.start_state

    def constrain_value_logits(self, logits, curr_state):
        first_value_token = self.num_functions + self.num_begin_tokens + self.num_control_tokens
        num_value_tokens = self.output_size - first_value_token
        value_allowed_token_matrix = np.concatenate((self.allowed_token_matrix[:,:self.num_control_tokens], self.allowed_token_matrix[:,first_value_token:]), axis=1)
        
        with tf.name_scope('constrain_logits'):
            allowed_tokens = tf.gather(tf.constant(value_allowed_token_matrix), curr_state)
            assert allowed_tokens.get_shape()[1:] == (self.num_control_tokens + num_value_tokens,)

            constrained_logits = logits - tf.to_float(tf.logical_not(allowed_tokens)) * 1e+10
        return constrained_logits

    def constrain_logits(self, logits, curr_state):
        with tf.name_scope('constrain_logits'):
            allowed_tokens = tf.gather(tf.constant(self.allowed_token_matrix), curr_state)
            assert allowed_tokens.get_shape()[1:] == (self.output_size,)

            constrained_logits = logits - tf.to_float(tf.logical_not(allowed_tokens)) * 1e+10
        return constrained_logits

    def value_transition(self, curr_state, next_symbols, batch_size):
        first_value_token = self.num_functions + self.num_begin_tokens + self.num_control_tokens
        num_value_tokens = self.output_size - first_value_token
        with tf.name_scope('grammar_transition'):
            adjusted_next_symbols = tf.where(next_symbols >= self.num_control_tokens, next_symbols + (first_value_token - self.num_control_tokens), next_symbols)
            
            assert1 = tf.Assert(tf.reduce_all(tf.logical_and(next_symbols < num_value_tokens, next_symbols >= 0)), [curr_state, next_symbols])
            with tf.control_dependencies([assert1]):
                transitions = tf.gather(tf.constant(self.transition_matrix), curr_state)
            assert transitions.get_shape()[1:] == (self.output_size,)
            
            indices = tf.stack((tf.range(0, batch_size), adjusted_next_symbols), axis=1)
            next_state = tf.gather_nd(transitions, indices)
            
            assert2 = tf.Assert(tf.reduce_all(next_state >= 0), [curr_state, adjusted_next_symbols, next_state])
            with tf.control_dependencies([assert2]):
                return tf.identity(next_state)

    def transition(self, curr_state, next_symbols, batch_size):
        with tf.name_scope('grammar_transition'):
            transitions = tf.gather(tf.constant(self.transition_matrix), curr_state)
            assert transitions.get_shape()[1:] == (self.output_size,)

            indices = tf.stack((tf.range(0, batch_size), next_symbols), axis=1)
            next_state = tf.gather_nd(transitions, indices)
            return next_state
    
    def _normalize_invocation(self, seq, start):
        assert self.tokens[seq[start]].startswith('tt:')
        if self.tokens[seq[start]].startswith('USERNAME_'):
            start += 1
        end = start
        
        params = []
        while end < len(seq) and seq[end] != self.end and self.tokens[seq[end]].startswith('tt-param:'):
            param_id = seq[end]
            end += 1
            if end >= len(seq) or seq[end] == self.end:
                # truncated output
                return end
            operator = seq[end]
            end += 1
            if end >= len(seq) or seq[end] == self.end:
                # this can occur at training time, if the output is truncated
                #raise AssertionError("missing value for " + self.tokens[param_id])
                params.append((param_id, operator, []))
                continue
            param_value = [seq[end]]
            end += 1
            while end < len(seq) and seq[end] != self.end and not self.tokens[seq[end]].startswith('tt:'):
                param_value.append(seq[end])
                end += 1
            params.append((param_id, operator, param_value))
        params.sort(key=lambda x: x[0])
        assert end <= len(seq)

        i = start
        for param_id, operator, param_value in params:
            seq[i] = param_id
            seq[i+1] = operator
            seq[i+2:i+2+len(param_value)] = param_value
            i += 2 + len(param_value)
            assert i <= end
        
        return end
    
    def normalize_sequence(self, seq):
        i = 0
        if seq[0] == self.dictionary['rule']:
            i += 1
            i = self._normalize_invocation(seq, i)
            if i < len(seq) and seq[i] != self.end:
                i = self._normalize_invocation(seq, i)
            if i < len(seq) and seq[i] != self.end:
                i = self._normalize_invocation(seq, i)
    
    def compare(self, gold, decoded):
        decoded = list(decoded)
        #self._normalize_sequence(decoded)
        return gold == decoded
        

if __name__ == '__main__':
    grammar = ThingtalkGrammar(sys.argv[1])
    #grammar.dump_tokens()
    #grammar.normalize_all(sys.stdin)
    matrix = grammar.parse_all(sys.stdin)
    print('Parsed', matrix.shape)
    np.save('programs.npy', matrix)
    #for i, name in enumerate(grammar.state_names):
    #    print i, name
