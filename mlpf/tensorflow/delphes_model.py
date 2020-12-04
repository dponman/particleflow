from tf_model import PFNet
import tensorflow as tf
import pickle
import numpy as np
import os
from sklearn.model_selection import train_test_split
import sys
import glob
#import PCGrad_tf
import io

import matplotlib
import matplotlib.pyplot as plt
import sklearn

num_input_classes = 2
num_output_classes = 6
mult_classification_loss = 1e1
mult_charge_loss = 1.0
mult_energy_loss = 0.1
mult_phi_loss = 1.0
mult_eta_loss = 1.0
mult_pt_loss = 0.1
mult_total_loss = 1e6

def mse_unreduced(true, pred):
    return tf.math.pow(true-pred,2)

def separate_prediction(y_pred):
    N = num_output_classes
    pred_id_logits = y_pred[:, :, :N]
    pred_charge = y_pred[:, :, N:N+1]
    pred_momentum = y_pred[:, :, N+1:]
    return pred_id_logits, pred_charge, pred_momentum

def separate_truth(y_true):
    true_id = tf.cast(y_true[:, :, :1], tf.int32)
    true_charge = y_true[:, :, 1:2]
    true_momentum = y_true[:, :, 2:]
    return true_id, true_charge, true_momentum

def accuracy(y_true, y_pred):
    pred_id_onehot, pred_charge, pred_momentum = separate_prediction(y_pred)
    pred_id = tf.cast(tf.argmax(pred_id_onehot, axis=-1), tf.int32)
    true_id, true_charge, true_momentum = separate_truth(y_true)

    is_true = true_id[:, :, 0]!=0
    is_same = true_id[:, :, 0] == pred_id

    acc = tf.reduce_sum(tf.cast(is_true&is_same, tf.int32)) / tf.reduce_sum(tf.cast(is_true, tf.int32))
    return tf.cast(acc, tf.float32)

def energy_resolution(y_true, y_pred):
    pred_id_onehot, pred_charge, pred_momentum = separate_prediction(y_pred)
    pred_id = tf.cast(tf.argmax(pred_id_onehot, axis=-1), tf.int32)
    true_id, true_charge, true_momentum = separate_truth(y_true)

    msk = true_id[:, :, 0]!=0
    return tf.reduce_mean(mse_unreduced(true_momentum[msk][:, -1], pred_momentum[msk][:, -1]))

def my_loss_full(y_true, y_pred):
    pred_id_logits, pred_charge, pred_momentum = separate_prediction(y_pred)
    #pred_id = tf.cast(tf.argmax(pred_id_logits, axis=-1), tf.int32)
    true_id, true_charge, true_momentum = separate_truth(y_true)
    true_id_onehot = tf.one_hot(tf.cast(true_id, tf.int32), depth=num_output_classes)
    
    l1 = mult_classification_loss*tf.nn.softmax_cross_entropy_with_logits(true_id_onehot, pred_id_logits)
  
    l2_0 = mult_pt_loss*mse_unreduced(true_momentum[:, :, 0], pred_momentum[:, :, 0])
    l2_1 = mult_eta_loss*mse_unreduced(true_momentum[:, :, 1], pred_momentum[:, :, 1])
    l2_2 = mult_phi_loss*mse_unreduced(true_momentum[:, :, 2], pred_momentum[:, :, 2])
    l2_3 = mult_phi_loss*mse_unreduced(true_momentum[:, :, 3], pred_momentum[:, :, 3])
    l2_4 = mult_energy_loss*mse_unreduced(true_momentum[:, :, 4], pred_momentum[:, :, 4])

    l2 = (l2_0 + l2_1 + l2_2 + l2_3 + l2_3)

    l3 = mult_charge_loss*mse_unreduced(true_charge, pred_charge)[:, :, 0]
    loss = l1 + l2 + l3

    # tf.print()
    # tf.print("cls", tf.reduce_mean(l1))
    # tf.print("pt", tf.reduce_mean(l2_0))
    # tf.print("eta", tf.reduce_mean(l2_1))
    # tf.print("sphi", tf.reduce_mean(l2_2))
    # tf.print("cphi", tf.reduce_mean(l2_3))
    # tf.print("e", tf.reduce_mean(l2_4))
    # tf.print("ch", tf.reduce_mean(l3))
    # tf.print()

    return mult_total_loss*loss

def plot_confusion_matrix(cm):
    fig = plt.figure(figsize=(5,5))
    plt.imshow(cm, cmap="Blues")
    plt.title("Reconstructed PID (normed to gen)")
    plt.xlabel("Delphes PF PID")
    plt.ylabel("Gen PID")
    plt.xticks(range(6), ["none", "ch.had", "n.had", "g", "el", "mu"]);
    plt.yticks(range(6), ["none", "ch.had", "n.had", "g", "el", "mu"]);
    plt.colorbar()
    return fig

def plot_regression(val_x, val_y, var_name, rng):
    fig = plt.figure(figsize=(5,5))
    plt.hist2d(
        val_x,
        val_y,
        bins=(rng, rng),
        cmap="Blues",
        norm=matplotlib.colors.LogNorm()
    );
    plt.xlabel("Gen {}".format(var_name))
    plt.ylabel("MLPF {}".format(var_name))
    return fig

def plot_to_image(figure):
    """
    Converts the matplotlib plot specified by 'figure' to a PNG image and
    returns it. The supplied figure is closed and inaccessible after this call.
    """
    
    buf = io.BytesIO()
    
    # Use plt.savefig to save the plot to a PNG in memory.
    plt.savefig(buf, format='png')
    plt.close(figure)
    buf.seek(0)
    
    image = tf.image.decode_png(buf.getvalue(), channels=4)
    image = tf.expand_dims(image, 0)
    
    return image

def plot_distributions(val_x, val_y, var_name, rng):
    fig = plt.figure(figsize=(5,5))
    plt.hist(val_x, bins=rng, density=True, histtype="step", lw=2, label="gen");
    plt.hist(val_y, bins=rng, density=True, histtype="step", lw=2, label="MLPF");
    plt.xlabel(var_name)
    plt.legend(loc="best", frameon=False)
    plt.ylim(0,1.5)
    return fig


def log_confusion_matrix(epoch, logs):
    
    test_pred, dm = model.predict(X_test, batch_size=5)
    test_pred_id = np.argmax(test_pred[:, :, :num_output_classes], axis=-1)

    cm = sklearn.metrics.confusion_matrix(
        y_test[:, :, 0].astype(np.int64).flatten(),
        test_pred_id.flatten(), labels=list(range(num_output_classes)))
    cm_normed = sklearn.metrics.confusion_matrix(
        y_test[:, :, 0].astype(np.int64).flatten(),
        test_pred_id.flatten(), labels=list(range(num_output_classes)), normalize="true")

    figure = plot_confusion_matrix(cm)
    cm_image = plot_to_image(figure)

    figure = plot_confusion_matrix(cm_normed)
    cm_image_normed = plot_to_image(figure)

    msk = (test_pred_id!=0) & (y_test[:, :, 0]!=0)
    ch_true = y_test[msk, 1].flatten()
    ch_pred = test_pred[msk, 1].flatten()

    pt_true = y_test[msk, 2].flatten()
    pt_pred = test_pred[msk, 2].flatten()

    e_true = y_test[msk, 6].flatten()
    e_pred = test_pred[msk, 6].flatten()

    eta_true = y_test[msk, 3].flatten()
    eta_pred = test_pred[msk, 3].flatten()

    sphi_true = y_test[msk, 4].flatten()
    sphi_pred = test_pred[msk, 4].flatten()

    cphi_true = y_test[msk, 5].flatten()
    cphi_pred = test_pred[msk, 5].flatten()

    figure = plot_regression(ch_true, ch_pred, "charge", np.linspace(-2, 2, 100))
    ch_image = plot_to_image(figure)

    figure = plot_regression(pt_true, pt_pred, "pt", np.linspace(0, 100, 100))
    pt_image = plot_to_image(figure)

    figure = plot_distributions(pt_true, pt_pred, "pt", np.linspace(0, 100, 100))
    pt_distr_image = plot_to_image(figure)

    figure = plot_regression(e_true, e_pred, "E", np.linspace(0, 100, 100))
    e_image = plot_to_image(figure)

    figure = plot_distributions(e_true, e_pred, "E", np.linspace(0, 100, 100))
    e_distr_image = plot_to_image(figure)

    figure = plot_regression(eta_true, eta_pred, "eta", np.linspace(-5, 5, 100))
    eta_image = plot_to_image(figure)

    figure = plot_distributions(eta_true, eta_pred, "eta", np.linspace(-5, 5, 100))
    eta_distr_image = plot_to_image(figure)

    figure = plot_regression(sphi_true, sphi_pred, "sin phi", np.linspace(-2, 2, 100))
    sphi_image = plot_to_image(figure)

    figure = plot_distributions(sphi_true, sphi_pred, "sin phi", np.linspace(-2, 2, 100))
    sphi_distr_image = plot_to_image(figure)

    figure = plot_regression(cphi_true, cphi_pred, "cos phi", np.linspace(-2, 2, 100))
    cphi_image = plot_to_image(figure)

    figure = plot_distributions(cphi_true, cphi_pred, "cos phi", np.linspace(-2, 2, 100))
    cphi_distr_image = plot_to_image(figure)

    with file_writer_cm.as_default():
        tf.summary.image("Confusion Matrix", cm_image, step=epoch)
        tf.summary.image("Confusion Matrix Normed", cm_image_normed, step=epoch)
        tf.summary.image("charge regression", ch_image, step=epoch)
        tf.summary.image("pT regression", pt_image, step=epoch)
        tf.summary.image("pT distibution", pt_distr_image, step=epoch)
        tf.summary.image("E regression", e_image, step=epoch)
        tf.summary.image("E distribution", e_distr_image, step=epoch)
        tf.summary.image("eta regression", eta_image, step=epoch)
        tf.summary.image("eta distribution", eta_distr_image, step=epoch)
        tf.summary.image("sin phi regression", sphi_image, step=epoch)
        tf.summary.image("sin phi distribution", sphi_distr_image, step=epoch)
        tf.summary.image("cos phi regression", cphi_image, step=epoch)
        tf.summary.image("cos phi distribution", cphi_distr_image, step=epoch)
        tf.summary.histogram("dm_values", dm.values, step=epoch)

def prepare_callbacks(model, outdir):
    callbacks = []
    tb = tf.keras.callbacks.TensorBoard(
        log_dir=outdir, histogram_freq=1, write_graph=False, write_images=False,
        update_freq='epoch',
        #profile_batch=(10,40),
        profile_batch=0,
    )
    tb.set_model(model)
    callbacks += [tb]

    terminate_cb = tf.keras.callbacks.TerminateOnNaN()
    callbacks += [terminate_cb]

    cp_callback = tf.keras.callbacks.ModelCheckpoint(
        filepath=outdir + "/weights.{epoch:02d}-{val_loss:.6f}.hdf5",
        save_weights_only=True,
        verbose=0
    )
    cp_callback.set_model(model)
    callbacks += [cp_callback]

    cm_callback = tf.keras.callbacks.LambdaCallback(on_epoch_end=log_confusion_matrix)
    callbacks += [cm_callback]

    return callbacks

def get_rundir(base='experiments'):
    if not os.path.exists(base):
        os.makedirs(base)

    previous_runs = os.listdir(base)
    if len(previous_runs) == 0:
        run_number = 1
    else:
        run_number = max([int(s.split('run_')[1]) for s in previous_runs]) + 1

    logdir = 'run_%02d' % run_number
    return '{}/{}'.format(base, logdir)

def compute_weights(y, mult=1.0):
    weights = np.ones((y.shape[0], y.shape[1]), dtype=np.float32)
    uniqs, counts = np.unique(y[:, :, 0], return_counts=True)

    #weight is inversely proportional to target particle PID frequency
    for val, c in zip(uniqs, counts):
        print("class {} count {}".format(val, c))
        weights[y[:, :, 0] == val] = mult / c

    return weights

# class MeanSquaredError(tf.keras.losses.Loss):

#   def call(self, y_true, y_pred):
#     #import pdb;pdb.set_trace()
#     y_pred = tf.convert_to_tensor_v2(y_pred)
#     y_true = tf.cast(y_true, y_pred.dtype)
#     return tf.reduce_mean(math_ops.square(y_pred - y_true), axis=-1)

def compute_weights_inverse(X, y, w):
    wn = 1.0/tf.sqrt(w)
    wn /= tf.reduce_sum(wn)
    return X, y, wn

if __name__ == "__main__":
    #tf.config.run_functions_eagerly(True)

    from delphes_data import _parse_tfr_element, padded_num_elem_size
    path = "out/pythia8_ttbar/tfr/*.tfrecords"
    tfr_files = glob.glob(path)
    if len(tfr_files) == 0:
        raise Exception("Could not find any files in {}".format(path))
        
    dataset = tf.data.TFRecordDataset(tfr_files).map(_parse_tfr_element, num_parallel_calls=tf.data.experimental.AUTOTUNE)
    num_events = 0
    for i in dataset:
        num_events += 1

    global_batch_size = 5
    n_train = int(0.5*num_events)
    n_test = int(0.5*num_events)
    n_epochs = 20

    ps = (tf.TensorShape([padded_num_elem_size, 9]), tf.TensorShape([padded_num_elem_size, 7]), tf.TensorShape([padded_num_elem_size, ]))
    ds_train = dataset.take(n_train).map(compute_weights_inverse).padded_batch(global_batch_size, padded_shapes=ps)
    ds_test = dataset.skip(n_train).take(n_test).map(compute_weights_inverse).padded_batch(global_batch_size, padded_shapes=ps)

    X_test = ds_test.take(100).map(lambda x,y,z: x)
    y_test = np.concatenate(list(ds_test.take(100).map(lambda x,y,z: y).as_numpy_iterator()))

    ds_train_r = ds_train.cache().repeat(n_epochs)
    ds_test_r = ds_test.cache().repeat(n_epochs)

    model = PFNet(
    	num_input_classes=num_input_classes, #(none, track, tower)
    	num_output_classes=num_output_classes, #(none, ch.had, n.had, gamma, el, mu)
    	num_momentum_outputs=5, #(log pT, eta, sin phi, cos phi, log E)
    	bin_size=256,
    	num_convs_id=2,
    	num_convs_reg=3,
        num_hidden_reg_enc=3,
        num_hidden_id_enc=0,
    	num_hidden_reg_dec=3,
    	num_hidden_id_dec=3,
        num_neighbors=16,
        hidden_dim_id=128,
        hidden_dim_reg=512,
        distance_dim=32,
        cosine_dist=False,
        dist_mult=1.0,
        return_combined=True,
        activation=tf.nn.selu,
    )

    outdir = get_rundir('experiments')
    if os.path.isdir(outdir):
        print("Output directory exists: {}".format(outdir), file=sys.stderr)
        sys.exit(1)
    
    file_writer_cm = tf.summary.create_file_writer(outdir + '/val_extra')
    callbacks = prepare_callbacks(model, outdir)

    #call the model once, to make sure it runs
    #model(X_train[:5])

    opt = tf.keras.optimizers.Adam(learning_rate=1e-3)

    #we use the "temporal" mode to have per-particle weights
    model.compile(
        loss=[my_loss_full, None],
        optimizer=opt,
        sample_weight_mode='temporal'
    )

    #model.load_weights("experiments/run_02/weights.10-121.166969.hdf5")
    #w_train = np.expand_dims(w_train, -1)
    #w_test = np.expand_dims(w_test, -1)

    model.fit(
        ds_train_r, validation_data=ds_test_r, epochs=n_epochs, callbacks=callbacks,
        steps_per_epoch=n_train/global_batch_size, validation_steps=n_test/global_batch_size
    )

    #y_pred, dm = model.predict(X, batch_size=5)
    #y_pred = np.concatenate(y_pred, axis=-1)
    #np.savez("{}/pred.npz".format(outdir), y_pred=y_pred)
