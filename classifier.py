# IMPORT PACKAGES AND FUNCTIONS
import tensorflow      as tf
import numpy           as np
import os, sys, h5py, pickle
from   argparse  import ArgumentParser
from   tabulate  import tabulate
from   itertools import accumulate
from   utils     import validation, make_sample, sample_composition, apply_scaler, load_scaler
from   utils     import compo_matrix, sample_weights, class_weights, balance_sample, split_samples
from   utils     import cross_valid, valid_results, sample_analysis, sample_histograms
from   models    import multi_CNN, callback, create_model


# PROGRAM ARGUMENTS
parser = ArgumentParser()
parser.add_argument( '--n_train'     , default =  10e6,  type = float)
parser.add_argument( '--n_valid'     , default =  10e6,  type = float)
parser.add_argument( '--batch_size'  , default =  5e3,  type = float )
parser.add_argument( '--n_epochs'    , default =  100,  type = int   )
parser.add_argument( '--n_classes'   , default =    2,  type = int   )
parser.add_argument( '--n_tracks'    , default =    5,  type = int   )
parser.add_argument( '--bkg_ratio'   , default =    2,  type = float )
parser.add_argument( '--n_folds'     , default =    1,  type = int   )
parser.add_argument( '--n_gpus'      , default =    4,  type = int   )
parser.add_argument( '--verbose'     , default =    1,  type = int   )
parser.add_argument( '--patience'    , default =   10,  type = int   )
parser.add_argument( '--sbatch_var'  , default =    0,  type = int   )
parser.add_argument( '--l2'          , default = 1e-7,  type = float )
parser.add_argument( '--dropout'     , default =  0.1,  type = float )
parser.add_argument( '--FCN_neurons' , default = [200,200], type = int, nargs='+')
parser.add_argument( '--weight_type' , default = 'none'              )
parser.add_argument( '--train_cuts'  , default = ''                  )
parser.add_argument( '--valid_cuts'  , default = ''                  )
parser.add_argument( '--NN_type'     , default = 'CNN'               )
parser.add_argument( '--images'      , default = 'ON'                )
parser.add_argument( '--scalars'     , default = 'ON'                )
parser.add_argument( '--scaling'     , default = 'ON'                )
parser.add_argument( '--plotting'    , default = 'OFF'               )
parser.add_argument( '--metrics'     , default = 'val_accuracy'      )
parser.add_argument( '--data_file'   , default = ''                  )
parser.add_argument( '--output_dir'  , default = 'outputs'           )
parser.add_argument( '--model_in'    , default = ''                  )
parser.add_argument( '--model_out'   , default = 'model.h5'          )
parser.add_argument( '--scaler_in'   , default = 'scaler.pkl'        )
parser.add_argument( '--scaler_out'  , default = 'scaler.pkl'        )
parser.add_argument( '--results_in'  , default = ''                  )
parser.add_argument( '--results_out' , default = ''                  )
parser.add_argument( '--runDiffPlots', default =  0, type = int      )

parser.add_argument( '--removal'     , default = 'OFF'               )
parser.add_argument( '--permutation' , default = 'OFF'               )
parser.add_argument( '--n_reps'      , default = 10, type = int      )
parser.add_argument( '--feat'        , default = -1, type = int      )
parser.add_argument( '--correlation' , default = 'OFF'               )
parser.add_argument( '--tracks_means', default = 'OFF'               )
parser.add_argument( '--auto_output_dir', default = 'OFF'            )

args = parser.parse_args()


# VERIFYING ARGUMENTS
for key in ['n_train', 'n_valid', 'batch_size']: vars(args)[key] = int(vars(args)[key])
if args.weight_type not in ['bkg_ratio', 'flattening', 'match2s', 'match2b', 'match2max', 'none']:
    print('\nweight_type: \"',args.weight_type,'\" not recognized, resetting it to none!!!')
    args.weight_type = 'none'
if '.h5' not in args.model_in and args.n_epochs < 1 and args.n_folds==1:
    print('\nERROR: weight file required with n_epochs < 1 -> exiting program\n'); sys.exit()

# DATAFILE
create_path(args.output_dir)
#if args.data_file == '': args.data_file = '/opt/tmp/godin/el_data/2019-06-20/0.0_1.3/output/el_data.h5'
if args.data_file in ['','barrel']:
#    args.data_file = '/opt/tmp/godin/el_data/2020-05-08/0.0_1.3/output/el_data.h5'
    args.data_file = '/scratch/odenis/el_data/0.0_1.3/el_data.h5'
    region = 'barrel'
if args.data_file == 'transition':
#    args.data_file = '/opt/tmp/godin/el_data/2020-05-08/1.3_1.6/output/el_data.h5'
    args.data_file = '/scratch/odenis/el_data/1.3_1.6/el_data.h5'
    region = 'transition'
if args.data_file == 'endcap':
#    args.data_file = '/opt/tmp/godin/el_data/2020-05-08/1.6_2.5/output/el_data.h5'
    args.data_file = '/scratch/odenis/el_data/1.6_2.5/el_data.h5'
    region = 'endcap'
#if args.data_file == '': args.data_file = '/project/def-arguinj/dgodin/el_data/2020-05-28/el_data.h5'
for key, val in h5py.File(args.data_file, 'r').items(): print(key, val.shape)

# CNN PARAMETERS
CNN = {(56,11):{'maps':[100,100], 'kernels':[ (3,5) , (3,5) ], 'pools':[ (4,1) , (2,1) ]},
        (7,11):{'maps':[100,100], 'kernels':[ (3,5) , (3,5) ], 'pools':[ (1,1) , (1,1) ]},
        #(7,11):{'maps':[200,200], 'kernels':[(3,5,7),(3,5,1)], 'pools':[(1,1,1),(1,1,1)]},
      'tracks':{'maps':[200,200], 'kernels':[ (1,1) , (1,1) ], 'pools':[ (1,1) , (1,1) ]}}

# TRAINING VARIABLES
scalars = ['p_Eratio', 'p_Reta'   , 'p_Rhad'     , 'p_Rphi'  , 'p_TRTPID' , 'p_numberOfSCTHits'           ,
           'p_ndof'  , 'p_dPOverP', 'p_deltaEta1', 'p_f1'    , 'p_f3'     , 'p_deltaPhiRescaled2'         ,
           'p_weta2' , 'p_d0'     , 'p_d0Sig'    , 'p_qd0Sig', 'p_nTracks', 'p_sct_weight_charge'         ,
           'p_eta'   , 'p_et_calo', 'p_EptRatio' , 'p_EoverP', 'p_wtots1' , 'p_numberOfInnermostPixelHits']
images  = ['em_barrel_Lr0'  , 'em_barrel_Lr1'  , 'em_barrel_Lr2'  , 'em_barrel_Lr3' , 'em_barrel_Lr1_fine',
           'em_endcap_Lr0'  , 'em_endcap_Lr1'  , 'em_endcap_Lr2'  , 'em_endcap_Lr3' , 'em_endcap_Lr1_fine',
           'lar_endcap_Lr0' , 'lar_endcap_Lr1' , 'lar_endcap_Lr2' , 'lar_endcap_Lr3', 'tile_gap_Lr1'      ,
           'tile_barrel_Lr1', 'tile_barrel_Lr2', 'tile_barrel_Lr3', 'tracks_image'                        ]
others  = ['mcChannelNumber', 'eventNumber', 'p_TruthType', 'p_iffTruth'   , 'p_TruthOrigin', 'p_LHValue' ,
           'p_LHTight'      , 'p_LHMedium' , 'p_LHLoose'  , 'p_ECIDSResult', 'p_eta'        , 'p_et_calo' ,
           'p_firstEgMotherTruthType'      , 'p_firstEgMotherTruthOrigin'  , 'correctedAverageMu'         ]
with h5py.File(args.data_file, 'r') as data:
    images  = [key for key in images  if key in data or key=='tracks_image']
    scalars = [key for key in scalars if key in data]
    others  = [key for key in others  if key in data]

###### update LaTeXizer in utils if changes are made to the intput variables. ######
groups  =  [['em_barrel_Lr1', 'em_barrel_Lr1_fine'], ['em_barrel_Lr0','em_barrel_Lr2', 'em_barrel_Lr3'],            # To compute the feature importance of a group of variables,
            ['em_endcap_Lr0','em_endcap_Lr2','em_endcap_Lr3'], ['em_endcap_Lr1' , 'em_endcap_Lr1_fine'],            # simply add the list of variables into groups.
            ['lar_endcap_Lr0','lar_endcap_Lr1','lar_endcap_Lr2','lar_endcap_Lr3'],
            ['tile_gap_Lr1' ,'tile_barrel_Lr1', 'tile_barrel_Lr2', 'tile_barrel_Lr3'],
            ['p_d0' , 'p_d0Sig'], ['p_d0' , 'p_d0Sig' , 'p_qd0Sig'], ['p_f1' , 'p_f3'],
            ['p_nTracks', 'p_sct_weight_charge'], ['p_nTracks', 'p_et_calo'],
            ['em_endcap_Lr2', 'tile_barrel_Lr1', 'p_f1', 'p_qd0Sig', 'p_TRTPID', 'em_endcap_Lr1_fine',
             'p_sct wt charge', 'p_wstot1', 'p_weta2', 'p_d0', 'p_d0Sig', 'tile_barrel_Lr3', 'em_endcap_Lr0',
             'em_endcap_Lr3', 'lar_endcap_Lr0', 'p_nTracks', 'tile_gap_Lr1', 'p_EptRatio', 'lar_endcap_Lr1',
             'p_dPOverP', 'p_numberOfSCTHits', 'lar_endcap_Lr3', 'p_Rphi' , 'p_f3', 'p_ndof', 'p_Eratio']]

if args.auto_output_dir == 'ON':
    args.output_dir = args.output_dir + '/{}c_{}m/{}/{}'.format(args.n_classes, round(args.n_train/1e6),            # Saves the output according to the number of classes, the stats used,
                                                            args.weight_type, region)                               # the reweighthing and the region

# FEATURE REMOVAL
if args.removal == 'ON':
    images, scalars, feat = feature_removal(args.feat, images, scalars, groups, args.images, args.scalars)
    args.output_dir = args.output_dir + '/removal_importance/' + feat                                               # The output directory will be different for each feature.
create_path(args.output_dir)                                                                                        # That way the model.h5 and their corresponding plots aren't mixed with
                                                                                                                    # the other trainings.
# FEATURE IMPORTANCE PLOTTING
if args.plotting in ['prm', 'permutation','rm', 'removal']:
    plot_importance(args.plotting, args.output_dir, region, images, scalars, len(groups), args.n_classes)
    sys.exit()

if args.scalars != 'ON': scalars=[]
if args.images  != 'ON': images =[]
if images == []: args.NN_type = 'FCN'
train_var = {'scalars':scalars, 'images':images}
variables = {**train_var, 'others':others}


# SAMPLES SIZES AND APPLIED CUTS ON PHYSICS VARIABLES
sample_size  = len(h5py.File(args.data_file, 'r')['mcChannelNumber'])
args.n_train = [0, min(sample_size, args.n_train)]
args.n_valid = [args.n_train[1], min(args.n_train[1]+args.n_valid, sample_size)]
if args.n_valid[0] == args.n_valid[1]: args.n_valid = args.n_train
#args.train_cuts += '(abs(sample["eta"]) > 0.8) & (abs(sample["eta"]) < 1.15)'
#args.valid_cuts += '(sample["p_et_calo"] > 4.5) & (sample["p_et_calo"] < 20)'


# OBTAINING PERFORMANCE FROM EXISTING VALIDATION RESULTS
if os.path.isfile(args.output_dir+'/'+args.results_in) or os.path.islink(args.output_dir+'/'+args.results_in):
    variables = {'scalars':scalars, 'images':[], 'others':others}
    validation(args.output_dir, args.results_in, args.plotting, args.n_valid,
               args.data_file, variables, args.n_classes, args.runDiffPlots)
elif args.results_in !='':
    print("\noption [--results_in] was given but no matching file found in the right path, aborting..")
    print("results_in file =", args.output_dir+'/'+args.results_in, '\n')
if args.results_in != '' : sys.exit()


# MODEL CREATION AND MULTI-GPU DISTRIBUTION
n_gpus = min(args.n_gpus, len(tf.config.experimental.list_physical_devices('GPU')))
sample = make_sample(args.data_file, variables, [0,1], args.n_tracks, args.n_classes)[0]
model  = create_model(args.n_classes, sample, args.NN_type, args.FCN_neurons, CNN,
                      args.l2, args.dropout, train_var, n_gpus)


# ARGUMENTS AND VARIABLES TABLES
args.scaler_in  = args.scaler_in  if '.pkl' in args.scaler_in  else ''
args.model_in   = args.model_in   if '.h5'  in args.model_in   else ''
args.results_in = args.results_in if '.h5'  in args.results_in else ''
args.scaling    = (args.scaling == 'ON' and scalars != [])
if args.NN_type == 'CNN':
    print('\nCNN ARCHITECTURES:')
    for shape in CNN: print(format(str(shape),'>8s')+':', str(CNN[shape]))
print('\nPROGRAM ARGUMENTS:'); print(tabulate(vars(args).items(), tablefmt='psql'))
print('\nTRAINING VARIABLES:')
headers = [          key  for key in train_var if train_var[key]!=[]]
table   = [train_var[key] for key in train_var if train_var[key]!=[]]
length  = max([len(n) for n in table])
table   = list(map(list, zip(*[n+(length-len(n))*[''] for n in table])))
print(tabulate(table, headers=headers, tablefmt='psql')); print()


# GENERATING VALIDATION SAMPLE AND LOADING PRE-TRAINED WEIGHTS
print('CLASSIFIER: loading valid sample', args.n_valid, end=' ... ', flush=True)
func_args = (args.data_file, variables, args.n_valid, args.n_tracks, args.n_classes, args.valid_cuts)
valid_sample, valid_labels = make_sample(*func_args)
#sample_analysis(valid_sample, valid_labels, scalars, args.scaler_in, args.output_dir); sys.exit()
if args.model_in != '':
    print('CLASSIFIER: loading pre-trained weights from', args.output_dir+'/'+args.model_in, '\n')
    model.load_weights(args.output_dir+'/'+args.model_in)
    if args.scaling: valid_sample = load_scaler(valid_sample, scalars, args.output_dir+'/'+args.scaler_in)


# EVALUATING CORRELATIONS
if args.correlation in ['ON','SCATTER']:
    correlations(images, scalars, valid_sample, valid_labels, region, args.output_dir + '/correlations/' + region + '/',
                 args.scaling, args.scaler_out, args.images, args.correlation, args.tracks_means)


# TRAINING LOOP
if args.n_epochs > 0:
    print('\nCLASSIFIER: train sample:'   , format(args.n_train[1] -args.n_train[0], '8.0f'), 'e')
    print(  'CLASSIFIER: valid sample:'   , format(args.n_valid[1] -args.n_valid[0], '8.0f'), 'e')
    print('\nCLASSIFIER: using TensorFlow', tf.__version__ )
    print(  'CLASSIFIER: using'           , n_gpus, 'GPU(s)')
    print(  'CLASSIFIER: using'           , args.NN_type, 'architecture with', end=' ')
    print([key for key in train_var if train_var[key] != []])
    print('\nCLASSIFIER: loading train sample', args.n_train, end=' ... ', flush=True)
    func_args = (args.data_file, variables, args.n_train, args.n_tracks, args.n_classes, args.train_cuts)
    train_sample, train_labels = make_sample(*func_args); sample_composition(train_sample)
    #sample_weight = sample_weights(train_sample,train_labels,args.n_classes,args.weight_type,args.output_dir)
    sample_weight = balance_sample(train_sample, train_labels, args.weight_type, args.bkg_ratio, hist='2d')[-1]
    sample_histograms(valid_sample, valid_labels, train_sample, train_labels, sample_weight, args.output_dir)
    if args.scaling:
        if args.model_in == '':
            scaler_out = args.output_dir+'/'+args.scaler_out; print()
            train_sample, valid_sample = apply_scaler(train_sample, valid_sample, scalars, scaler_out)
        else: print(); train_sample = load_scaler(train_sample, scalars, args.output_dir+'/'+args.scaler_in)
    print(); compo_matrix(valid_labels, train_labels=train_labels); print()
    model_out = args.output_dir+'/'+args.model_out
    training  = model.fit( train_sample, train_labels, validation_data=(valid_sample,valid_labels),
                           callbacks=callback(model_out, args.patience, args.metrics),
                           sample_weight=sample_weight, batch_size=max(1,n_gpus)*int(args.batch_size),
                           epochs=args.n_epochs, verbose=args.verbose )
    model.load_weights(model_out)
else: train_labels = []; training = None


# RESULTS AND PLOTTING SECTION
if args.n_folds > 1:
    valid_probs = cross_valid(valid_sample, valid_labels, scalars, model, args.output_dir, args.n_folds)
    print('MERGING ALL FOLDS AND PREDICTING CLASSES ...')
else:
    print('\nValidation sample', args.n_valid, 'class predictions:')
    valid_probs = model.predict(valid_sample, batch_size=20000, verbose=args.verbose); print()
bkg_rej_full = valid_results(valid_sample, valid_labels, valid_probs, train_labels, training,
              args.output_dir, args.plotting, args.runDiffPlots, args.n_classes)
#print('bkg_rej_full[0]',bkg_rej_full[0], type(bkg_rej_full[0])) # FOR DEVELOPING PURPOSES
if args.results_out != '':
    print('Saving validation results to:', args.output_dir+'/'+args.results_out, '\n')
    if args.n_folds > 1 and False: valid_data = (valid_probs,)
    else: valid_data = ({key:valid_sample[key] for key in others+['eta','pt']}, valid_labels, valid_probs)
    pickle.dump(valid_data, open(args.output_dir+'/'+args.results_out,'wb'))


# FEATURE IMPORTANCE
if args.removal == 'ON': bkg_rej_full = (feat, bkg_rej_full)
fname = args.output_dir + '/bkg_rej' # Saves the 70% bkg_rej into a pkl for later use
saving_results(bkg_rej_full, fname)

# FEATURE PERMUTATION IMPORTANCE
if args.permutation == 'ON':
    feats = [[var] for var in images + scalars]
    g = args.feat-len(feats)
    feats += groups
    feature_permutation(feats[args.feat], g, valid_sample, valid_labels, model, bkg_rej_full, train_labels,
                        training, args.n_classes, args.n_reps, args.output_dir)
