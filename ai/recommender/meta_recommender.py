"""
Recommender system for Penn AI.
"""
import pandas as pd
import json 
import urllib.request, urllib.parse
from .base import BaseRecommender
#from ..metalearning import get_metafeatures
from xgboost import XGBRegressor
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
from sklearn.pipeline import Pipeline
import numpy as np
from collections import defaultdict, OrderedDict
import pdb

class MetaRecommender(BaseRecommender):
    """Penn AI meta recommender.
    Recommends machine learning algorithms and parameters as follows:
    maintains an internal model of the form f_d(ML,P,MF) = E
    where 
    d is the dataset
    ML is the machine learning
    P is the ML parameters
    MF is the metafeatures associated with d
        
    to produce recommendations for dataset d, it does the following:
    E_a = f_d(ML_a,P_a,MF_d) prediction of performance of a on d
    Sort E_a for several a (sampled from ML+P options)
    recommend top E_a 

    Parameters
    ----------
    ml_type: str, 'classifier' or 'regressor'
        Recommending classifiers or regressors. Used to determine ML options.
    
    metric: str (default: accuracy for classifiers, mse for regressors)
        The metric by which to assess performance on the datasets.
    
    ml_p: Dataframe
        Contains all the machine learning / algorithm combinations available for recommendation.

    sample_size: int
        Number of ML/P combos to evaluate when making a recommendation. 

    """
    def __init__(self, ml_type='classifier', metric=None, ml_p=None,
                 sample_size=100):
        """Initialize recommendation system."""
        if ml_type not in ['classifier', 'regressor']:
            raise ValueError('ml_type must be "classifier" or "regressor"')

        self.ml_type = ml_type

        if metric is None:
            self.metric = 'bal_accuracy' if self.ml_type == 'classifier' else 'mse'
        else:
            self.metric = metric
        
        # training data
        self.training_features = None
        # store metafeatures of datasets that have been seen
        # self.dataset_metafeatures = None
        # maintain a set of dataset-algorithm-parameter combinations that have already been 
        # evaluated
        self.trained_dataset_models = set()
        # TODO: add option for ML estimator
        self.first_update = True

	# load ML Parameter combinations and fit an encoding to them that can be used for
	# learning a model : score = f(ml,p,dataset,metafeatures)
       
        self.ml_p = ml_p
        if self.ml_p is not None:
            self.ml_p = self.params_to_features(self.ml_p, init=True)
            self.ml_p = self.ml_p.drop_duplicates() # just in case duplicates are present
        
        # print('ml_p:',self.ml_p)
        self.cat_params = ['criterion', 'kernel', 'loss', 'max_depth', 'max_features',
                           'min_weight_fraction_leaf', 'n_estimators', 'n_neighbors', 'weights']

        self.sample_size = min(sample_size, len(self.ml_p))
        # Encoding the variables
        self.LE = defaultdict(LabelEncoder)
        # self.OHE = OneHotEncoder(sparse=False)
        # pdb.set_trace()
        self.ml_p = self.ml_p.apply(lambda x: self.LE[x.name].fit_transform(x))
        # print('ml_p after LE:',self.ml_p)
        # self.X_ml_p = self.OHE.fit_transform(self.ml_p.values)
        self.X_ml_p = self.ml_p.values
        # self.ml_p = self.ml_p.apply(lambda x: self.OHE[x.name].fit_transform(x))
        # print('X after OHE:',self.X_ml_p.shape)
        # print('self.ml_p:',self.ml_p)
        print('loaded {nalg} ml/parameter combinations with '
                '{nparams} parameters'.format(nalg=self.X_ml_p.shape[0],
                                                     nparams=self.X_ml_p.shape[1]-1))

        # our ML
        self.ml = XGBRegressor(max_depth=6,n_estimators=500)

    def params_to_features(self, df, init=False):
        """convert parameter dictionaries to dataframe columns"""
        # pdb.set_trace()
        try:
            param = df['parameters'].apply(eval)
            param = pd.DataFrame.from_records(list(param))
            param = param.applymap(str)
            # get rid of trailing .0 added to integer vals 
            param = param.applymap(lambda x: x[:-2] if x[-2:] == '.0' else x)
            param = param.reset_index(drop=True)
            # print('param:',param)
            df = df.drop('parameters',axis=1).reset_index(drop=True)
            df = pd.concat([df, param],axis=1)

            if not init: # need to add additional parameter combos for other ml
                df_tmp = pd.DataFrame(columns=self.ml_p.columns)
                df_tmp = df_tmp.append(df)
                df_tmp.fillna('nan', inplace=True)
                df = df_tmp
            # sort columns by name 
            df.sort_index(axis=1, inplace=True)
            # print('df:',df)
        except Exception as e:
            print(e)
            pdb.set_trace() 
        return df

    def features_to_params(self, df ):
        """convert dataframe columns to parameter dictionaries"""
        param = df.to_dict('index')
        plist = []
        for k,v in param.items():
            tmp = {k1:v1 for k1,v1 in v.items() if v1 != 'nan'}
            for k1,v1 in tmp.items():
                try:
                    tmp[k1] = int(v1)
                except:
                    try:
                        tmp[k1] = float(v1)
                    except:
                        pass
                    pass
            plist.append(str(tmp))

        return plist 


    def update(self, results_data, results_mf):
        """Update ML / Parameter recommendations based on overall performance in results_data.

        Updates self.scores

        Parameters
        ----------
        results_data: DataFrame with columns corresponding to:
                'dataset'
                'algorithm'
                'parameters'
                self.metric
        """
        # keep track of unique dataset / parameter / classifier combos in results_data
        dap = (results_data['dataset'].values + '|' +
               results_data['algorithm'].values + '|' +
               results_data['parameters'].values)
        d_ml_p = np.unique(dap)
        self.trained_dataset_models.update(d_ml_p)
        # transform data for learning a model from it 
        self.setup_training_data(results_data, results_mf) 

        # update internal model
        self.update_model()

    def transform_ml_p(self,df_ml_p):
        """Encodes categorical labels and transforms them using a one hot encoding."""
        df_ml_p = self.params_to_features(df_ml_p)
        # df_tmp = pd.DataFrame(columns=self.ml_p.columns)
        # df_tmp = df_tmp.append(df_ml_p)
        # df_tmp.fillna('nan', inplace=True)
        df_ml_p = df_ml_p.apply(lambda x: self.LE[x.name].transform(x))
        # df_ml_p = df_ml_p.apply(lambda x: self.LE[x.name].transform(x))

        # print('df_ml_p after LE transform:',df_ml_p)
        # X_ml_p = self.OHE.transform(df_ml_p.values)
        X_ml_p = df_ml_p.values
        # X_ml_p = self.OHE.transform(df_ml_p.values)
        # print('df_ml_p after OHE (',X_ml_p.shape,':\n',X_ml_p)
        return X_ml_p

    def setup_training_data(self, results_data, results_mf):
        """Transforms metafeatures and results data into learnable format."""
        # join df_mf to results_data to get mf rows for each result
        df_mf = pd.merge(results_data, results_mf, on='dataset', how='inner')
        df_mf = df_mf.loc[:,df_mf.columns.isin(results_mf.columns)]
        if 'dataset' in df_mf.columns: 
            df_mf = df_mf.drop('dataset',axis=1)
        # print('df_mf:',df_mf)
        # print('dataset_metafeatures:',dataset_metafeatures)
        # transform algorithms and parameters to one hot encoding 
        df_ml_p = results_data.loc[:, results_data.columns.isin(['algorithm','parameters'])]
        X_ml_p = self.transform_ml_p(df_ml_p)
        print('df_ml_p shape:',df_ml_p.shape)
        # join algorithm/parameters with dataset metafeatures
        print('df_mf shape:',df_mf.shape) 
        self.training_features = np.hstack((X_ml_p,df_mf.values))
        # transform data using label encoder and one hot encoder
        self.training_y = results_data[self.metric].values
        assert(len(self.training_y)==len(self.training_features))
         
    def recommend(self, dataset_id=None, n_recs=1, dataset_mf=None):
        """Return a model and parameter values expected to do best on dataset.

        Parameters
        ----------
        dataset_id: string
            ID of the dataset for which the recommender is generating recommendations.
        n_recs: int (default: 1), optional
            Return a list of length n_recs in order of estimators and parameters expected to do best.
        """
        # TODO: predict scores over many variations of ML+P and pick the best
        # return ML+P for best average y
        try:
            ml_rec, p_rec, rec_score = self.best_model_prediction(dataset_id, n_recs,
                                                                  dataset_mf)

            for (m,p,r) in zip(ml_rec, p_rec, rec_score):
                print('ml_rec:', m, 'p_rec', p, 'rec_score',r)
            ml_rec, p_rec, rec_score = ml_rec[:n_recs], p_rec[:n_recs], rec_score[:n_recs]
            # # if a dataset is specified, do not make recommendations for
            # # algorithm-parameter combos that have already been run
            # if dataset_id is not None:
            #     rec = [r for r in rec if dataset_id + '|' + r not in
            #            self.trained_dataset_models]

            # ml_rec = [r.split('|')[0] for r in rec]
            # p_rec = [r.split('|')[1] for r in rec]
            # rec_score = [self.scores[r] for r in rec]
        except Exception as e:
            print( 'error running self.best_model_prediction for',dataset_id)
            # print('ml_rec:', ml_rec)
            # print('p_rec', p_rec)
            # print('rec_score',rec_score)
            raise e 

        # update the recommender's memory with the new algorithm-parameter combos that it recommended
        # ml_rec = ml_rec[:n_recs]
        # p_rec = p_rec[:n_recs]
        # rec_score = rec_score[:n_recs]

        # if dataset_id is not None:
        #     self.trained_dataset_models.update(
        #                                 ['|'.join([dataset_id, ml, p])
        #                                 for ml, p in zip(ml_rec, p_rec)])

        return ml_rec, p_rec, rec_score

    def update_model(self):
        """Trains model on datasets and metafeatures."""
        print('updating model')
        current_model = None if self.ml._Booster is None else self.ml.get_booster()
        self.ml.fit(self.training_features, self.training_y, xgb_model = current_model)
        print('model updated')

    def best_model_prediction(self,dataset_id, n_recs=1, df_mf=None):
        """Predict scores over many variations of ML+P and pick the best"""
        # get dataset metafeatures
        # df_mf = self.get_metafeatures(dataset_id) 
        mf = df_mf.drop('dataset',axis=1).values.flatten()
        # setup input data by sampling ml+p combinations from all possible combos 
        # choices = np.random.choice(len(self.X_ml_p),size=self.sample_size,replace=False)
        X_ml_p = self.X_ml_p[np.random.choice(len(self.X_ml_p),size=self.sample_size,replace=False)]
        print('generating predictions for:')
        df_tmp = pd.DataFrame(X_ml_p,columns=self.ml_p.columns)
        print(df_tmp.apply(lambda x: self.LE[x.name].inverse_transform(x)))
        # make prediction data consisting of ml + p combinations plus metafeatures
        predict_features = np.array([np.hstack((ml_p, mf)) for ml_p in X_ml_p])
        
        # print('predict_features:',predict_features)
        # generate predicted scores
        predict_scores = self.ml.predict(predict_features)
        # print('predict_scores:',predict_scores)

        # grab best scores
        predict_idx = np.argsort(predict_scores)[::-1][:n_recs]
        # print('predict_idx:',predict_idx) 
        # indices in X_ml_p that match best prediction scores
        predict_ml_p = X_ml_p[predict_idx]
        pred_ml_p_df = df_tmp.loc[predict_idx,:]
        # print('df_tmp[predict_idx]:',pred_ml_p_df)
        # invert the one hot encoding
        # fi = self.OHE.feature_indices_
        # predict_ml_p_le = [x[fi[i]:fi[i+1]].dot(np.arange(nv)) for i,nv in 
        #                    enumerate(self.OHE.n_values_) 
        #                    for x in predict_ml_p]
        predict_ml_p_le = predict_ml_p

        # df_pr_ml_p = pd.DataFrame(
        #         data=np.array(predict_ml_p_le).reshape(-1,len(self.ml_p.columns)),
        #         columns = self.ml_p.columns, dtype=np.int64)
        # # invert the label encoding 
        df_pr_ml_p = df_tmp.loc[predict_idx,:]
        df_pr_ml_p = df_pr_ml_p.apply(lambda x: self.LE[x.name].inverse_transform(x))
        # predict_ml_p = df_pr_ml_p.values

        # grab recommendations
        ml_recs = list(df_pr_ml_p['algorithm'].values)
        p_recs = self.features_to_params(df_pr_ml_p.drop('algorithm',axis=1))
        scores = predict_scores[predict_idx]
        # pdb.set_trace()

        return ml_recs,p_recs,scores
        
