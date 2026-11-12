from copy import deepcopy
from typing import Any, List, Mapping, Tuple
import numpy as np
from citylearn.agents.rbc import RBC
from citylearn.agents.sac import SACRBC
from citylearn.citylearn import CityLearnEnv

try:
    from sklearn.decomposition import PCA
    from sklearn.linear_model import LinearRegression
except (ModuleNotFoundError, ImportError) as e:
    raise Exception("This functionality requires you to install scikit-learn. You can install scikit-learn by : pip scikit-learn, or for more detailed instructions please visit https://scikit-learn.org/stable/install.html.")

try:
    import torch
except (ModuleNotFoundError, ImportError) as e:
    raise Exception("This functionality requires you to install torch. You can install torch by : pip install torch torchvision, or for more detailed instructions please visit https://pytorch.org.")

from citylearn.agents.sac import SAC
from citylearn.preprocessing import Encoder, NoNormalization, PeriodicNormalization, RemoveFeature
from citylearn.rl import RegressionBuffer

class MARLISA(SAC):
    __COORDINATION_VARIABLE_COUNT = 2

    def __init__(
        self, *args, regression_buffer_capacity: int = None, start_regression_time_step: int = None, 
        regression_frequency: int = None, information_sharing: bool = None, pca_compression: float = None, iterations: int = None, **kwargs
    ):
        self.__coordination_variables_history = None
        self.__pending_transitions = None
        self.__start_regression_time_step = None
        self.information_sharing = information_sharing

        super().__init__(*args, **kwargs)

        self.regression_buffer_capacity = regression_buffer_capacity
        self.start_regression_time_step = start_regression_time_step
        self.pca_compression = pca_compression
        self.iterations = iterations
        self.regression_frequency = regression_frequency

        # internally defined
        self.regression_buffer = [RegressionBuffer(int(self.regression_buffer_capacity)) for _ in self.action_space]
        self.state_estimator = [LinearRegression() for _ in self.action_space]
        self.pca = [None for _ in self.action_space]
        self.pca_flag = [False for _ in self.action_dimension]
        self.regression_flag = [0 for _ in self.action_dimension]
        self.__regression_sample_count = [0 for _ in self.action_dimension]
        self.energy_size_coefficient = None
        self.total_coefficient = None
        self.regression_encoders = self.set_regression_encoders()
        self.set_energy_coefficients()
        self.set_pca()
        self.set_training_schedule(
            batch_size=kwargs.get('batch_size'), standardize_start_time_step=kwargs.get('standardize_start_time_step'),
            end_exploration_time_step=kwargs.get('end_exploration_time_step'),
        )

    @property
    def regression_buffer_capacity(self) -> int:
        return self.__regression_buffer_capacity

    @property
    def start_regression_time_step(self) -> int:
        return self.__start_regression_time_step

    @property
    def regression_frequency(self) -> int:
        return self.__regression_frequency

    @property
    def information_sharing(self) -> bool:
        return self.__information_sharing

    @property
    def pca_compression(self) -> float:
        return self.__pca_compression

    @property
    def iterations(self) -> int:
        return self.__iterations

    @property
    def coordination_variables_history(self) -> List[float]:
        return self.__coordination_variables_history

    @SAC.hidden_dimension.setter
    def hidden_dimension(self, hidden_dimension: List[float]):
        hidden_dimension = [400, 300] if hidden_dimension is None else hidden_dimension
        SAC.hidden_dimension.fset(self, hidden_dimension)

    @SAC.batch_size.setter
    def batch_size(self, batch_size: int):
        batch_size = 100 if batch_size is None else batch_size
        SAC.batch_size.fset(self, batch_size)

    @regression_buffer_capacity.setter
    def regression_buffer_capacity(self, regression_buffer_capacity: int):
        self.__regression_buffer_capacity = 3e4 if regression_buffer_capacity is None else regression_buffer_capacity

    @regression_frequency.setter
    def regression_frequency(self, regression_frequency: int):
        self.__regression_frequency = 2500 if regression_frequency is None else regression_frequency

    @start_regression_time_step.setter
    def start_regression_time_step(self, start_regression_time_step: int):
        default_time_step = 2
        start_regression_time_step = default_time_step if start_regression_time_step is None else start_regression_time_step
        assert start_regression_time_step < self.standardize_start_time_step, 'start_regression_time_step must be < standardize_start_time_step'
        self.__start_regression_time_step = start_regression_time_step

    @information_sharing.setter
    def information_sharing(self, information_sharing: bool):
        self.__information_sharing = True if information_sharing is None else information_sharing

    @pca_compression.setter
    def pca_compression(self, pca_compression: float):
        self.__pca_compression = 1.0 if pca_compression is None else pca_compression

    @iterations.setter
    def iterations(self, iterations: int):
        self.__iterations = 2 if iterations is None else iterations

    def update(self, observations: List[List[float]], actions: List[List[float]], reward: List[float], next_observations: List[List[float]], terminated: bool, truncated: bool):
        r"""Update replay buffer.

        Parameters
        ----------
        observations : List[List[float]]
            Previous time step observations.
        actions : List[List[float]]
            Previous time step actions.
        reward : List[float]
            Current time step reward.
        next_observations : List[List[float]]
            Current time step observations.
        terminated : bool
            Indication that episode has ended.
        truncated : bool
            If episode truncates due to a time limit or a reason that is not defined as part of the task MDP.
        """

        # Run once the regression model has been fitted
        # Normalize all the observations using periodical normalization, one-hot encoding, or -1, 1 scaling. It also removes observations that are not necessary (solar irradiance if there are no solar PV panels).

        # The coordination variables in history[1] were computed with the actions for `observations` (latest predict),
        # so they belong to `observations`, and to the next observation of the transition held back at the last step.
        for i, (o, a, r, n, c) in enumerate(zip(observations, actions, reward, next_observations, self.coordination_variables_history[1])):
            if self.information_sharing:
                # update regression buffer
                variables = np.hstack(np.concatenate((self.get_encoded_regression_variables(i, o), a)))
                # The targets are the net electricity consumption.
                target = self.get_encoded_regression_targets(i, n)
                self.regression_buffer[i].push(variables, target)

                if self.__pending_transitions[i] is not None:
                    po, pa, pr, pn, pd = self.__pending_transitions[i]
                    self.__pending_transitions[i] = None
                    self.__push_transition(i, po, pa, pr, np.hstack(np.concatenate((pn, c), dtype=float)), pd)

                else:
                    pass

            else:
                pass

            if self.regression_flag[i] > 1:
                o = self.get_encoded_observations(i, o)
                n = self.get_encoded_observations(i, n)

                if self.information_sharing:
                    o = np.hstack(np.concatenate((o, c), dtype=float))

                    if terminated or truncated:
                        # No action, hence no coordination variables, is computed for the episode's final observation,
                        # so c stands in for them (as before); they do not enter the TD target when terminated.
                        self.__push_transition(i, o, a, r, np.hstack(np.concatenate((n, c), dtype=float)), terminated)

                    else:
                        # The coordination variables of n are computed with the next action: push at the next update.
                        self.__pending_transitions[i] = (o, a, r, n, terminated)

                else:
                    self.__push_transition(i, o, a, r, n, terminated)

            else:
                pass

            # Refit whenever the regression buffer has doubled since the last fit, until a fit has used
            # regression_frequency samples; from then on every regression_frequency time steps.
            sample_count = len(self.regression_buffer[i])
            sparse_refit = self.information_sharing\
                and self.__regression_sample_count[i] < self.regression_frequency\
                    and sample_count >= 2*self.__regression_sample_count[i]

            if self.time_step >= self.start_regression_time_step\
                and (self.regression_flag[i] < 2 or self.time_step%self.regression_frequency == 0 or sparse_refit):
                if self.information_sharing:
                    self.state_estimator[i].fit(self.regression_buffer[i].x, self.regression_buffer[i].y)
                    self.__regression_sample_count[i] = sample_count

                else:
                    pass

                if self.regression_flag[i] < 2:
                    self.regression_flag[i] += 1
                
                else:
                    pass

            else:
                pass

            if self.time_step >= self.standardize_start_time_step and self.batch_size <= len(self.replay_buffer[i]):
                # This code only runs once. Once the random exploration phase is over, we normalize all the states and rewards to make them have mean=0 and std=1, and apply PCA. We push the normalized compressed values back into the buffer, replacing the old buffer.
                if not self.pca_flag[i]:
                    # calculate normalized observations and rewards
                    X = np.array([j[0] for j in self.replay_buffer[i].buffer], dtype=float)
                    self.norm_mean[i] = np.nanmean(X, axis=0)
                    self.norm_std[i] = self.get_normalization_scale(np.nanstd(X, axis=0))
                    X = self.get_normalized_observations(i, X)
                    self.pca[i].fit(X)

                    R = np.array([j[2] for j in self.replay_buffer[i].buffer], dtype=float)
                    self.r_norm_mean[i] = np.nanmean(R, dtype=float)
                    self.r_norm_std[i] = self.get_normalization_scale(np.nanstd(R, dtype=float)/self.reward_scaling)

                    # update buffer with normalization
                    self.replay_buffer[i].buffer = [(
                        np.hstack(self.pca[i].transform(self.get_normalized_observations(i, o).reshape(1,-1))[0]),
                        a,
                        self.get_normalized_reward(i, r),
                        np.hstack(self.pca[i].transform(self.get_normalized_observations(i, n).reshape(1,-1))[0]),
                        d
                    ) for o, a, r, n, d in self.replay_buffer[i].buffer]
                    self.pca_flag[i] = True
                    self.normalized[i] = True
                
                else:
                    pass

                for _ in range(self.update_per_time_step):
                    o, a, r, n, d = self.replay_buffer[i].sample(self.batch_size)
                    tensor = torch.cuda.FloatTensor if self.device.type == 'cuda' else torch.FloatTensor
                    o = tensor(o).to(self.device)
                    n = tensor(n).to(self.device)
                    a = tensor(a).to(self.device)
                    r = tensor(r).unsqueeze(1).to(self.device)
                    d = tensor(d).unsqueeze(1).to(self.device)

                    with torch.no_grad():
                        # Update Q-values. First, sample an action from the Gaussian policy/distribution for the current (next) observation and its associated log probability of occurrence.
                        new_next_actions, new_log_pi, _ = self.policy_net[i].sample(n)

                        # The updated Q-value is found by subtracting the logprob of the sampled action (proportional to the entropy) to the Q-values estimated by the target networks.
                        target_q_values = torch.min(
                            self.target_soft_q_net1[i](n, new_next_actions),
                            self.target_soft_q_net2[i](n, new_next_actions),
                        ) - self.alpha*new_log_pi
                        q_target = r + (1 - d)*self.discount*target_q_values

                    # Update Soft Q-Networks
                    q1_pred = self.soft_q_net1[i](o, a)
                    q2_pred = self.soft_q_net2[i](o, a)
                    q1_loss = self.soft_q_criterion(q1_pred, q_target)
                    q2_loss = self.soft_q_criterion(q2_pred, q_target)
                    self.soft_q_optimizer1[i].zero_grad()
                    q1_loss.backward()
                    self.soft_q_optimizer1[i].step()
                    self.soft_q_optimizer2[i].zero_grad()
                    q2_loss.backward()
                    self.soft_q_optimizer2[i].step()

                    # Update Policy
                    new_actions, log_pi, _ = self.policy_net[i].sample(o)
                    q_new_actions = torch.min(
                        self.soft_q_net1[i](o, new_actions),
                        self.soft_q_net2[i](o, new_actions)
                    )
                    policy_loss = (self.alpha*log_pi - q_new_actions).mean()
                    self.policy_optimizer[i].zero_grad()
                    policy_loss.backward()
                    self.policy_optimizer[i].step()

                    # Soft Updates
                    for target_param, param in zip(self.target_soft_q_net1[i].parameters(), self.soft_q_net1[i].parameters()):
                        target_param.data.copy_(target_param.data*(1.0 - self.tau) + param.data*self.tau)

                    for target_param, param in zip(self.target_soft_q_net2[i].parameters(), self.soft_q_net2[i].parameters()):
                        target_param.data.copy_(target_param.data*(1.0 - self.tau) + param.data*self.tau)

            else:
                pass

    def get_post_exploration_prediction(self, observations: List[List[float]], deterministic: bool) -> List[List[float]]:
        func = {
            True: self.get_post_exploration_prediction_with_information_sharing,
            False: self.get_post_exploration_prediction_without_information_sharing
        }[self.information_sharing]
        actions, coordination_variables = func(observations, deterministic)
        self.__coordination_variables_history[0] = deepcopy(self.__coordination_variables_history[1])
        self.__coordination_variables_history[1] = coordination_variables[0:]
        
        return actions

    def get_exploration_prediction(self, observations: List[List[float]]) -> List[List[float]]:
        func = {
            True: self.get_exploration_prediction_with_information_sharing,
            False: self.get_exploration_prediction_without_information_sharing
        }[self.information_sharing]
        actions, coordination_variables = func(observations)
        self.__coordination_variables_history[0] = deepcopy(self.__coordination_variables_history[1])
        self.__coordination_variables_history[1] = coordination_variables[0:]
        
        return actions

    def get_post_exploration_prediction_with_information_sharing(self, observations: List[List[float]], deterministic: bool) -> Tuple[List[List[float]], List[List[float]]]:
        agent_count = len(self.action_dimension)
        actions = [None for _ in range(agent_count)]
        action_order = list(range(agent_count))
        next_agent_ixs = [sorted(action_order)[action_order[(i + 1)%agent_count]] for i in range(agent_count)]
        coordination_variables = [[0.0, 0.0] for _ in range(agent_count)] 
        expected_demand = [0.0 for _ in range(agent_count)]
        total_demand = 0.0
        
        for i in range(self.iterations):
            capacity_dispatched = 0.0

            for c, n, o, o_ in zip(action_order, next_agent_ixs, observations, observations):
                o = self.get_encoded_observations(c, o)
                o = np.hstack(np.concatenate((o, coordination_variables[c])))
                o = self.get_normalized_observations(c, o)
                o = self.pca[c].transform(o.reshape(1,-1))[0]
                o = torch.FloatTensor(o).unsqueeze(0).to(self.device)
                result = self.policy_net[i].sample(o)
                a = result[2] if deterministic else result[0]
                a = list(a.detach().cpu().numpy()[0])
                actions[c] = a
                expected_demand[c] = self.predict_demand(c, o_, a)

                if i == self.iterations - 1 and c == action_order[-1]:
                    pass
                else:
                    total_demand += expected_demand[c] - expected_demand[n]
                    coordination_variables[n][0] = total_demand/self.total_coefficient

                coordination_variables[c][1] = capacity_dispatched
                capacity_dispatched += self.energy_size_coefficient[c]
        
        return actions, coordination_variables

    def get_post_exploration_prediction_without_information_sharing(self, observations: List[List[float]], deterministic: bool) -> Tuple[List[List[float]], List[List[float]]]:
        agent_count = len(self.action_dimension)
        actions = [None for _ in range(agent_count)]
        coordination_variables = [[0.0, 0.0] for _ in range(agent_count)]

        for i, o in enumerate(observations):
            o = self.get_encoded_observations(i, o)
            o = self.get_normalized_observations(i, o)
            o = self.pca[i].transform(o.reshape(1,-1))[0]
            o = torch.FloatTensor(o).unsqueeze(0).to(self.device)
            result = self.policy_net[i].sample(o)
            a = result[2] if deterministic else result[0]
            a = list(a.detach().cpu().numpy()[0])
            actions[i] = a
        
        return actions, coordination_variables

    def get_exploration_prediction_with_information_sharing(self, observations: List[List[float]]) -> Tuple[List[List[float]], List[List[float]]]:
        actions, coordination_variables = self.get_exploration_prediction_without_information_sharing(observations)
    
        if self.time_step > self.start_regression_time_step:
            agent_count = len(self.action_dimension)
            action_order = list(range(agent_count))
            nprs = np.random.RandomState(int(self.random_seed + self.time_step))
            nprs.shuffle(action_order)
            expected_demand = [self.predict_demand(i, o, a) for i, (o, a) in enumerate(zip(observations, actions))]
            coordination_variables = [[
                (sum(expected_demand) - expected_demand[i])/self.total_coefficient,
                sum([self.energy_size_coefficient[j] for j in action_order[0:action_order.index(i)]])
            ] for i in range(agent_count)]
        
        else:
            pass
        
        return actions, coordination_variables

    def get_exploration_prediction_without_information_sharing(self, observations: List[List[float]]) -> Tuple[List[List[float]], List[List[float]]]:
        actions = super().get_exploration_prediction(observations)
        coordination_variables = [[0.0, 0.0] for _ in range(len(self.action_dimension))]

        return actions, coordination_variables

    def predict_demand(self, index: int, observations: List[float], actions: List[float]) -> float:
        return self.state_estimator[index].predict(self.get_regression_variables(index, observations, actions).reshape(1, -1))[0]
    
    def get_regression_variables(self, index: int, observations: List[float], actions: List[float]) -> List[float]:
        return np.hstack(np.concatenate((self.get_encoded_regression_variables(index, observations), actions)))

    def get_encoded_regression_variables(self, index: int, observations: List[float]) -> List[float]:
        net_electricity_consumption_ix = self.observation_names[index].index('net_electricity_consumption')
        o = observations[0:]
        del o[net_electricity_consumption_ix]
        e = self.regression_encoders[index][0:]
        del e[net_electricity_consumption_ix]
        
        return np.array([j for j in np.hstack(e*np.array(o, dtype=float)) if j != None], dtype=float).tolist()

    def get_encoded_regression_targets(self, index: int, observations: List[float]) -> float:
        net_electricity_consumption_ix = self.observation_names[index].index('net_electricity_consumption')
        o = observations[net_electricity_consumption_ix]
        e = self.regression_encoders[index][net_electricity_consumption_ix]
        
        return e*o

    def set_pca(self):
        addition = self.__COORDINATION_VARIABLE_COUNT if self.information_sharing else 0
        
        for i, s in enumerate(self.observation_space):
            n_components = int((self.pca_compression)*(addition + len(self.get_encoded_observations(i, s.low))))
            self.pca[i] = PCA(n_components=n_components, random_state=self._get_seed(3, i))

    def set_energy_coefficients(self):
        self.energy_size_coefficient = []
        self.total_coefficient = 0

        for b in self.building_metadata:
            coef = b['annual_dhw_demand_estimate']/.9 \
                + b['annual_cooling_demand_estimate']/3.5 \
                    + b['annual_heating_demand_estimate']/3.5 \
                        + b['annual_non_shiftable_load_estimate'] \
                            - b['annual_solar_generation_estimate']/6.0
            coef = max(0.3*(coef + b['annual_solar_generation_estimate']/6.0), coef)/8760
            self.energy_size_coefficient.append(coef)
            self.total_coefficient += coef

        self.energy_size_coefficient = [c/self.total_coefficient for c in self.energy_size_coefficient]

    def set_regression_encoders(self) -> List[List[Encoder]]:
        r"""Get observation value transformers/encoders for use in MARLISA agent internal regression model.

        The encoder classes are defined in the `preprocessing.py` module and include `PeriodicNormalization` for cyclic observations,
        `OnehotEncoding` for categorical obeservations, `RemoveFeature` for non-applicable observations given available storage systems and devices
        and `Normalize` for observations with known minimum and maximum boundaries.
        
        Returns
        -------
        encoders : List[Encoder]
            Encoder classes for observations ordered with respect to `active_observations`.
        """

        encoders = []
        remove_features = [
            'outdoor_dry_bulb_temperature', 'outdoor_dry_bulb_temperature_predicted_1',
            'outdoor_dry_bulb_temperature_predicted_2','outdoor_dry_bulb_temperature_predicted_3',
            'outdoor_relative_humidity', 'outdoor_relative_humidity_predicted_1',
            'outdoor_relative_humidity_predicted_2','outdoor_relative_humidity_predicted_3',
            'diffuse_solar_irradiance', 'diffuse_solar_irradiance_predicted_1',
            'diffuse_solar_irradiance_predicted_2', 'diffuse_solar_irradiance_predicted_3',
            'direct_solar_irradiance', 'direct_solar_irradiance_predicted_1',
            'direct_solar_irradiance_predicted_2', 'direct_solar_irradiance_predicted_3',
        ]

        for o, s in zip(self.observation_names, self.observation_space):
            e = []

            for i, n in enumerate(o):
                if n in ['month', 'hour']:
                    e.append(PeriodicNormalization(s.high[i]))
            
                elif n in remove_features:
                    e.append(RemoveFeature())
            
                else:
                    e.append(NoNormalization())

            encoders.append(e)

        return encoders

    def set_networks(self):
        internal_observation_count = self.__COORDINATION_VARIABLE_COUNT if self.information_sharing else 0
        return super().set_networks(internal_observation_count=internal_observation_count)

    def set_training_schedule(self, *args, **kwargs):
        # SAC.__init__ calls this before start_regression_time_step exists; MARLISA.__init__ calls it again afterwards.
        if self.start_regression_time_step is not None:
            super().set_training_schedule(*args, **kwargs)

        else:
            pass

    @property
    def _replay_buffer_delay(self) -> int:
        # Transitions enter the replay buffer once the state estimator has been fitted twice (regression_flag > 1),
        # i.e. from the update at time step max(start_regression_time_step, 1) + 2; with information sharing, each
        # waits one more update for the coordination variables of its next observation.
        return max(self.start_regression_time_step, 1) + 1 + int(self.information_sharing)

    @property
    def _minimum_standardization_size(self) -> int:
        # PCA is fitted on the standardized replay buffer and needs at least n_components samples.
        return max([1] + [p.n_components for p in self.pca])

    def __push_transition(self, index: int, o, a, r, n, terminated: bool):
        # Executed during the training phase. States and rewards pushed into the replay buffer are normalized and processed using PCA.
        if self.pca_flag[index]:
            o = self.get_normalized_observations(index, o)
            o = self.pca[index].transform(o.reshape(1, -1))[0]
            n = self.get_normalized_observations(index, n)
            n = self.pca[index].transform(n.reshape(1, -1))[0]
            r = self.get_normalized_reward(index, r)

        else:
            pass

        self.replay_buffer[index].push(o, a, r, n, terminated)

    def __setstate__(self, state: Mapping[str, Any]):
        super().__setstate__(state)

        # Checkpoints from CityLearn <= 3.2.0 lack these. Their state estimator may have been fitted on as few as 2
        # samples: with no fit counted, it is refitted on the whole regression buffer at the next update, then as the
        # buffer grows. No transition is held back.
        if '_MARLISA__regression_sample_count' not in state:
            self.__regression_sample_count = [0 for _ in self.action_dimension]

        if '_MARLISA__pending_transitions' not in state:
            self.__pending_transitions = [None for _ in self.action_dimension]

    def reset(self):
        super().reset()
        self.__coordination_variables_history = [
            [[0.0]*self.__COORDINATION_VARIABLE_COUNT for _ in self.action_dimension] for _ in range(2)
        ]
        self.__pending_transitions = [None for _ in self.action_dimension]

class MARLISARBC(MARLISA, SACRBC):
    r"""Uses :py:class:`citylearn.agents.rbc.RBC` to select action during exploration before using :py:class:`citylearn.agents.marlisa.MARLISA`.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    rbc: RBC
        :py:class:`citylearn.agents.rbc.RBC` or child class, used to select actions during exploration.
    
    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, env: CityLearnEnv, rbc: RBC = None, **kwargs: Any):
        super().__init__(env=env, rbc=rbc, **kwargs)

    def get_exploration_prediction_without_information_sharing(self, observations: List[List[float]]) -> Tuple[List[List[float]], List[List[float]]]:
        _, coordination_variables = super().get_exploration_prediction_without_information_sharing(observations)
        actions = super(SACRBC, self).get_exploration_prediction(observations)

        return actions, coordination_variables