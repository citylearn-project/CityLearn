import concurrent.futures
import random
from typing import List, Tuple
from doe_xstock.end_use_load_profiles import EndUseLoadProfiles
import math
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import cluster as cluster_metrics
from sklearn.preprocessing import MinMaxScaler
from citylearn.base import Environment

class Clustering:
    __MINIMUM_BUILDING_COUNT = 3

    def __init__(self, end_use_load_profiles: EndUseLoadProfiles, bldg_ids: List[int], maximum_clusters: int = None, sum_of_squares_error_minimum_percent_change: float = None, random_seed: int = None) -> None:
        self.end_use_load_profiles = end_use_load_profiles
        self.bldg_ids = bldg_ids
        self.maximum_clusters = maximum_clusters
        self.sum_of_squares_error_minimum_percent_change = sum_of_squares_error_minimum_percent_change
        self.random_seed = random_seed

    @property
    def maximum_clusters(self) -> int:
        return self.__maximum_clusters
    
    @property
    def bldg_ids(self) -> List[int]:
        return self.__bldg_ids
    
    @property
    def sum_of_squares_error_minimum_percent_change(self) -> float:
        return self.__sum_of_squares_error_minimum_percent_change
    
    @property
    def random_seed(self) -> int:
        return self.__random_seed
    
    @bldg_ids.setter
    def bldg_ids(self, value: List[int]):
        assert len(value) > self.__MINIMUM_BUILDING_COUNT, f'Provide at least {self.__MINIMUM_BUILDING_COUNT} bldg_ids.'
        self.__bldg_ids = sorted(value)
    
    @maximum_clusters.setter
    def maximum_clusters(self, value: int):
        value = math.ceil(len(self.bldg_ids)/2) if value is None else value
        assert 2 <= value < len(self.bldg_ids), f'maximum_clusters must be > 2 and less than number of bldg_ids'
        self.__maximum_clusters = value

    @sum_of_squares_error_minimum_percent_change.setter
    def sum_of_squares_error_minimum_percent_change(self, value: float):
        self.__sum_of_squares_error_minimum_percent_change = 10.0 if value is None else value

    @random_seed.setter
    def random_seed(self, value: int):
        self.__random_seed = random.randint(*Environment.DEFAULT_RANDOM_SEED_RANGE) if value is None else value

    def cluster(self) -> Tuple[int, pd.DataFrame, pd.DataFrame]:
        data = self.set_data()
        scaler = MinMaxScaler()
        scaler.fit(data)
        data = scaler.transform(data)
        scores = []
        labels = []

        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = {executor.submit(self.__cluster, *(data, c)): c for c in range(2, self.maximum_clusters + 1)}
        
            for future in concurrent.futures.as_completed(results):
                try:
                    clusters = results[future]
                    _labels, sum_of_squares_error, calinski_harabasz_score, silhouette_score, davies_bouldin_score = future.result()
                    scores.append({
                        'clusters': clusters,
                        'sum_of_square_error': sum_of_squares_error,
                        'calinski_harabasz_score': calinski_harabasz_score,
                        'silhouette_score': silhouette_score,
                        'davies_bouldin_score': davies_bouldin_score
                    })
                    labels.append(pd.DataFrame({
                        'clusters': clusters,
                        'bldg_id': self.bldg_ids,
                        'label': _labels
                    }))

                except Exception as e:
                    raise(e)

        scores = pd.DataFrame(scores).sort_values('clusters')
        labels = pd.concat(labels, ignore_index=True)
        optimal_clusters = self.get_optimal_clusters(*scores.T.values)

        return optimal_clusters, scores, labels
    
    def get_optimal_clusters(self, clusters: List[int], sum_of_squares_error: List[float], calinski_harabasz_score: List[float], silhouette_score: List[float], davies_bouldin_score: List[float]) -> int:
        assert len(clusters) == len(sum_of_squares_error) == len(calinski_harabasz_score) == len(davies_bouldin_score), \
            'clusters and scores lists must have equal lengths.'
        sum_of_squares_error_change = (
            np.array(sum_of_squares_error, dtype=float)[:-1] 
            - np.array(sum_of_squares_error, dtype=float)[1:]
        )*100/np.array(sum_of_squares_error, dtype=float)[:-1]
        sse_candidates = np.array(clusters[:-1], dtype=int)[  # noqa: F841 (used by the disabled criterion below)
            sum_of_squares_error_change < self.sum_of_squares_error_minimum_percent_change
        ]
        optimal_clusters = np.nanmean([
            # sse_candidates.min() if len(sse_candidates) > 0 else np.nan,
            clusters[np.array(calinski_harabasz_score, dtype=float).argmax()],
            clusters[np.array(silhouette_score, dtype=float).argmax()],
            clusters[np.array(davies_bouldin_score, dtype=float).argmin()],

        ], dtype=float)
        optimal_clusters = math.floor(optimal_clusters)
        
        return optimal_clusters

    def __cluster(self, data: np.ndarray, clusters: int):
        model = KMeans(clusters, random_state=self.random_seed).fit(data)
        labels = model.labels_
        sum_of_squares_error = model.inertia_
        calinski_harabasz_score = cluster_metrics.calinski_harabasz_score(data, model.labels_)
        davies_bouldin_score = cluster_metrics.davies_bouldin_score(data, model.labels_)
        silhouette_score = cluster_metrics.silhouette_score(data, model.labels_)

        return labels, sum_of_squares_error, calinski_harabasz_score, silhouette_score, davies_bouldin_score
    
    def set_data(self) -> pd.DataFrame:
        raise NotImplementedError

class MetadataClustering(Clustering):
    def __init__(self, end_use_load_profiles: EndUseLoadProfiles, bldg_ids: List[int], maximum_clusters: int = None, sum_of_squares_error_minimum_percent_change: float = None, random_seed: int = None):
        super().__init__(
            end_use_load_profiles, 
            bldg_ids, 
            maximum_clusters=maximum_clusters,
            sum_of_squares_error_minimum_percent_change=sum_of_squares_error_minimum_percent_change,
            random_seed=random_seed,
        )

    def set_data(self) -> pd.DataFrame:
        data = self.end_use_load_profiles.metadata.metadata.get()
        data = data[data.index.isin(self.bldg_ids)].copy()
        clustering_columns = [
            'in.window_to_wall_ratio',
            'in.vintage',
            'in.orientation_hour_sin',
            'in.orientation_hour_cos',
            'in.infiltration',
            'in.insulation_ceiling',
            'in.insulation_slab',
            'in.insulation_wall',
            'out.site_energy.total.energy_consumption_intensity',
        ]

        # window-to-wall ratio
        data['in.window_to_wall_ratio'] = data['in.window_area_ft_2']/data['in.wall_area_above_grade_exterior_ft_2']

        # vintage
        data['in.vintage'] = data['in.vintage'].replace('\D', '', regex=True).astype(int)

        # orientation: cosine transformation
        order = ['North', 'Northeast', 'East', 'Southeast', 'South', 'Southwest', 'West', 'Northwest']
        data['in.orientation'] = data['in.orientation'].map(lambda x: order.index(x))
        data['in.orientation_hour_sin'] = np.sin(2 * np.pi * data['in.orientation']/(len(order)-1))
        data['in.orientation_hour_cos'] = np.cos(2 * np.pi * data['in.orientation']/(len(order)-1))
        data = data.drop(columns=['in.orientation'])

        # infiltration
        data['in.infiltration'] = data['in.infiltration'].replace(regex=r' ACH50', value='')
        data['in.infiltration'] = pd.to_numeric(data['in.infiltration'], errors='coerce')
        data['in.infiltration'] = data['in.infiltration'].fillna(0)

        # insulation ceiling
        data['in.insulation_ceiling'] = data['in.insulation_ceiling'].replace(regex=r'R-', value='')
        data['in.insulation_ceiling'] = pd.to_numeric(data['in.insulation_ceiling'], errors='coerce')
        data['in.insulation_ceiling'] = data['in.insulation_ceiling'].fillna(0)

        # insulation slab
        data.loc[data['in.insulation_slab'].isin(['None', 'Uninsulated']), 'in.insulation_slab'] = 'Uninsulated R0'
        data['in.insulation_slab'] = data['in.insulation_slab'].str.split(' ', expand=True)[1]
        data['in.insulation_slab'] = data['in.insulation_slab'].replace(regex=r'R', value='')
        data['in.insulation_slab'] = pd.to_numeric(data['in.insulation_slab'], errors='coerce')
        data['in.insulation_slab'] = data['in.insulation_slab'].fillna(0)

        # insulation wall
        data['in.insulation_wall'] = data['in.insulation_wall'].replace(regex=r'.+ R-', value='')
        data['in.insulation_wall'] = pd.to_numeric(data['in.insulation_wall'], errors='coerce')
        data['in.insulation_wall'] = data['in.insulation_wall'].fillna(0)

        data = data[clustering_columns].astype(float)

        return data