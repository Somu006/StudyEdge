import numpy as np
import pickle

class LSTMLayer:
    def __init__(self, input_dim, hidden_dim):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        
        # Gates: i, f, c, o (Keras order)
        self.W = np.zeros((hidden_dim * 4, input_dim))
        self.U = np.zeros((hidden_dim * 4, hidden_dim))
        self.b = np.zeros((hidden_dim * 4, 1))

    def sigmoid(self, x):
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

    def forward(self, x_seq):
        # x_seq shape: (seq_len, input_dim)
        seq_len = x_seq.shape[0]
        h = np.zeros((self.hidden_dim, 1))
        c = np.zeros((self.hidden_dim, 1))
        h_seq = []

        for t in range(seq_len):
            xt = x_seq[t].reshape(-1, 1)
            
            # gates = [i, f, c, o]
            gates = np.dot(self.W, xt) + np.dot(self.U, h) + self.b
            
            i = self.sigmoid(gates[0:self.hidden_dim])
            f = self.sigmoid(gates[self.hidden_dim:2*self.hidden_dim])
            c_tilde = np.tanh(gates[2*self.hidden_dim:3*self.hidden_dim])
            o = self.sigmoid(gates[3*self.hidden_dim:4*self.hidden_dim])
            
            c = f * c + i * c_tilde
            h = o * np.tanh(c)
            h_seq.append(h.flatten())
            
        return np.array(h_seq) # shape: (seq_len, hidden_dim)

class StackedPureLSTM:
    def __init__(self, layer_dims):
        # layer_dims: [input_dim, h1, h2, ..., output_dim]
        self.layers = []
        for i in range(len(layer_dims) - 2):
            self.layers.append(LSTMLayer(layer_dims[i], layer_dims[i+1]))
        
        # Final Dense layer
        self.Wy = np.zeros((layer_dims[-1], layer_dims[-2]))
        self.by = np.zeros((layer_dims[-1], 1))

    def forward(self, x):
        # x shape: (seq_len, input_dim)
        current_input = x
        for layer in self.layers:
            current_input = layer.forward(current_input)
        
        # Use only the last hidden state of the last LSTM layer
        last_h = current_input[-1].reshape(-1, 1)
        y = np.dot(self.Wy, last_h) + self.by
        return y.flatten()[0]

    def save(self, path):
        with open(path, 'wb') as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
