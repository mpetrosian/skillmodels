"""Functions to simulate a dataset generated by a latent factor model.

Notes:
    - I use abbreviations to describe the sizes of arrays. An overview is here:
        https://skillmodels.readthedocs.io/en/latest/names_and_concepts.html
    - what is called factors here is the same as states in the assignments.
    - You can use additional functions if you want. Their name should start
        with an underscore to make clear that those functions should not be
        used in any other module.
    - Please write tests for all functions except simulate_dataset.
        I know that functions involving randomness are hard to test. The
        best way is to replace (patch) the methods that actually generate
        random numbers with a so called mock function while testing. It can
        be done with this library:
        https://docs.python.org/3/library/unittest.mock.html
        I do similar stuff in many places of skillmodels but it is quite difficult,
        so you can also ask me once you get there and we can do it together.
    - The tests should be in a module in
        `skillmodels/tests/simulation/simulate_dataset_test.py.
    - Use pytest for the tests (as you learned in the lecture) even though
        the other tests in skillmodels use an older library
    - I added some import statements but you will probably need more
    - Please delete all notes in the docstrings when you are done.
    - It is very likely that I made some mistakes in the docstrings or forgot an
        argument somewhere. Just send me an email in that case or come to my office.
"""
import sys
import pandas as pd
import numpy as np
from numpy.random import multivariate_normal, choice, binomial

sys.path.append("../../")
import model_functions.transition_functions as tf
import simulation._elliptical_functions as ef


def add_missings(data, meas_names, p_b, p_r):
    """Add np.nans to data.

    nans are only added to measurements, not to control variables or factors.

    The function does not modify data in place. (create a new one)

    Args:
        data (pd.DataFrame): contains the observable part of a simulated dataset
        meas_names (list): list of strings of names of each measurement variable
        p_b (float): probability of a measurement to become missing
        p_r (float): probability of a measurement to remain missing in the next period
    Returns:
        data_with_missings (pd.DataFrame): Dataset with a share of measurements
        replaced by np.nan values

    Notes:
        - Time_periods should be sorted for each individual
        - p is NOT the marginal probability of a measurement being missing.
          The marginal probability is given by: p_m = p/(1-serial_corr), where
          serial_corr = (p_r-p_b) in general != 0, since p_r != p_b. This means that in
          average the share of missing values (in the entire dataset) will be larger
          than p. Thus, p and q should be set accordingly given the desired share
          of missing values.
        - I would still suggest to draw period_0 bernoulli with the marginal
          probaility. Having run the function in a loop with 100 iteration, for
          100 pairs of p_r and p_b , the average share of missing measurements in all
          measurements is very close to p_b/(1-(p_r-p_b)) (the average percentage
          deviation is less than 2 %). Sounds like a nice result and a simple
          formula for deciding on p_b and p_r.
    """

    nmeas = len(meas_names)
    data_with_missings = data.copy(deep=True)
    for i in set(data_with_missings.index):
        ind_data = data_with_missings.loc[i][meas_names].values
        s_0 = binomial(1, p_b, nmeas)
        ind_data[0, np.where(s_0 == 1)] = np.nan
        for t in range(1, len(ind_data)):
            indc_nan = np.isnan(ind_data[t - 1])
            prob = p_r * indc_nan + p_b * (1 - indc_nan)
            s_m = binomial(1, prob)
            ind_data[t, np.where(s_m == 1)] = np.nan
        data_with_missings.loc[i, meas_names] = ind_data

    return data_with_missings


def simulate_datasets(
    factor_names,
    control_names,
    meas_names,
    nobs,
    nper,
    transition_names,
    transition_argument_dicts,
    shock_variances,
    loadings,
    deltas,
    meas_variances,
    dist_name,
    dist_arg_dict,
    weights=1,
):
    """Simulate datasets generated by a latent factor model.

    This function calls the remaining functions in this module.

    Args:
         nper (int): number of time periods the dataset contains
         nobs (int): number of observations
         factor_names (list): list of strings of names of each factor
         control_names (list): list of strings of names of each control variable
         meas_names (list): list of strings of names of each measurement variable
         loadings (np.ndarray): numpy array of size (nmeas, nfac)
         deltas (np.ndarray): numpy array of size (nmeas, ncontrols)
         transition_names (list): list of strings with the names of the transition
            function of each factor.
         transition_argument_dicts (list): list of dictionaries of length nfac with
            the arguments for the transition function of each factor. A detailed description
            of the arguments of transition functions can be found in the module docstring
            of skillmodels.model_functions.transition_functions.
         shock_variances (np.ndarray): numpy array of length nfac.
         meas_variances (np.ndarray): numpy array of size (nmeas) with the variances of the
            measurements. Measurement error is assumed to be independent across measurements
         dist_name (string): the elliptical distribution to use in the mixture
         dist_arg_dict (list or dict): list of length nemf of dictionaries with the 
          relevant arguments of the mixture distributions. Arguments with default
          values should NOT be included in the dictionaries. Lengths of arrays in the
          arguments should be in accordance with nfac + ncont
         weights (np.ndarray): size (nemf). The weight of each mixture element.
               The default value is 1.

    Returns:
        observed_data (pd.DataFrame): Dataset with measurements and control variables
            in long format
        latent_data (pd.DataFrame): Dataset with lantent factors in long format
    Notes:
        - the key names of dist_arg_dict can be looked up in the module
          _elliptical_functions. For multivariate_normal it's [mean, cov].
    """
    ncont = len(control_names)
    nfac = len(factor_names)
    fac = [np.zeros((nobs, nfac))] * nper
    # array of id_s repeated n_per times
    obs_id = np.tile(np.arange(nobs), nper)

    fac[0], cont = generate_start_factors_and_control_variables_elliptical(
        nobs, nfac, ncont, dist_name, dist_arg_dict, weights
    )

    cont = pd.DataFrame(
        data=np.array([cont] * nper).reshape(nobs * nper, ncont),
        columns=control_names,
        index=obs_id,
    )

    for i in range(1, nper):
        fac[i] = next_period_factors(
            fac[i - 1], transition_names, transition_argument_dicts, shock_variances
        )

    meas = pd.DataFrame(
        data=measurements_from_factors(
            np.array(fac).reshape(nobs * nper, nfac),
            cont.values,
            loadings,
            deltas,
            meas_variances,
        ),
        columns=meas_names,
        index=obs_id,
    )

    t_col = pd.DataFrame(
        np.repeat(range(nper), nobs), columns=["time_period"], index=obs_id
    )

    observed_data = pd.concat([t_col, meas, cont], axis=1)
    latent_data = pd.DataFrame(
        data=np.array(fac).reshape(nobs * nper, nfac),
        columns=factor_names,
        index=obs_id,
    )

    latent_data = pd.concat([t_col, latent_data], axis=1)

    return observed_data, latent_data


def generate_start_factors_and_control_variables(
    nobs, nfac, ncont, means, covs, weights=1
):
    """Draw initial states and control variables from a (mixture of) normals.

    Args:
        nobs (int): number of observations
        nfac (int): number of factor (latent) variables
        ncont (int): number of control variables
        means (np.ndarray): size (nemf, nfac + ncontrols)
        covs (np.ndarray): size (nemf, nfac + ncontrols, nfac + ncontrols)
        weights (np.ndarray): size (nemf). The weight of each mixture element.
                              Default value is equal to 1.


    Returns:
        start_factors (np.ndarray): shape (nobs, nfac),
        controls (np.ndarray): shape (nobs, ncontrols),
    """

    if np.size(weights) == 1:
        out = multivariate_normal(means, covs, nobs)
    else:
        helper_array = choice(np.arange(len(weights)), p=weights, size=nobs)
        out = np.zeros((nobs, nfac + ncont))
        for i in range(nobs):
            out[i] = multivariate_normal(means[helper_array[i]], covs[helper_array[i]])
    start_factors = out[:, 0:nfac]
    controls = out[:, nfac:]

    return start_factors, controls


def generate_start_factors_and_control_variables_elliptical(
    nobs, nfac, ncont, dist_name, dist_arg_dict, weights=1
):
    """Draw initial states and control variables from a (mixture of) normals.

    Args:
        nobs (int): number of observations
        nfac (int): number of factor (latent) variables
        ncont (int): number of control variables
        dist_name (string): the elliptical distribution to use in the mixture
        dist_arg_dict (list or dict): list of length nemf of dictionaries with the 
          relevant arguments of the mixture distributions. Arguments with default
          values should NOT be included in the dictionaries. Lengths of arrays in the
          arguments should be in accordance with nfac + ncont
        weights (np.ndarray): size (nemf). The weight of each mixture element.
                              Default value is equal to 1.

    Returns:
        start_factors (np.ndarray): shape (nobs, nfac),
        controls (np.ndarray): shape (nobs, ncontrols),
    """

    if np.size(weights) == 1:
        out = getattr(ef, dist_name)(**dist_arg_dict, size=nobs)
    else:
        helper_array = choice(np.arange(len(weights)), p=weights, size=nobs)
        out = np.zeros((nobs, nfac + ncont))
        for i in range(nobs):
            out[i] = getattr(ef, dist_name)(**dist_arg_dict[helper_array[i]])
    start_factors = out[:, 0:nfac]
    controls = out[:, nfac:]

    return start_factors, controls


def next_period_factors(
    factors, transition_names, transition_argument_dicts, shock_variances
):
    """Apply transition function to factors and add shocks.

    Args:
        factors (np.ndarray): shape (nobs, nfac)
        transition_names (list): list of strings with the names of the transition
            function of each factor.
        transition_argument_dicts (list): list of dictionaries of length nfac with
            the arguments for the transition function of each factor. A detailed description
            of the arguments of transition functions can be found in the module docstring
            of skillmodels.model_functions.transition_functions.
        shock_variances (np.ndarray): numpy array of length nfac.

    Returns:
        next_factors (np.ndarray): shape(nobs,nfac)
    """
    nobs, nfac = factors.shape
    # sigma_points = factors
    factors_tp1 = np.zeros((nobs, nfac))
    for i in range(nfac):
        factors_tp1[:, i] = getattr(tf, transition_names[i])(
            factors, **transition_argument_dicts[i]
        )
    # Assumption: In general err_{Obs_j,Fac_i}!=err{Obs_k,Fac_i}, where j!=k
    errors = multivariate_normal([0] * nfac, np.diag(shock_variances), nobs).reshape(
        nobs, nfac
    )
    next_factors = factors_tp1 + errors

    return next_factors


def measurements_from_factors(factors, controls, loadings, deltas, variances):
    """Generate the variables that would be observed in practice.

    This generates the data for only one period. Let nmeas be the number
    of measurements in that period.

    Args:
        factors (pd.DataFrame or np.ndarray): DataFrame of shape (nobs, nfac)
        controls (pd.DataFrame or np.ndarray): DataFrame of shape (nobs, ncontrols)
        loadings (np.ndarray): numpy array of size (nmeas, nfac)
        deltas (np.ndarray): numpy array of size (nmeas, ncontrols)
        variances (np.ndarray): numpy array of size (nmeas) with the variances of the
            measurements. Measurement error is assumed to be independent across measurements

    Returns:
        measurements (np.ndarray): array of shape (nobs, nmeas) with measurements.
    """
    nmeas = loadings.shape[0]
    nobs, nfac = factors.shape
    ncontrols = controls.shape[1]
    # Assumption: In general eps_{Obs_j,Meas_i}!=eps_{Obs_k,Meas_i}  where j!=k
    epsilon = multivariate_normal([0] * nmeas, np.diag(variances), nobs).reshape(
        nobs, 1, nmeas
    )
    states = factors.reshape(nobs, 1, nfac)
    conts = controls.reshape(nobs, 1, ncontrols)
    meas = np.dot(states, loadings.T) + np.dot(conts, deltas.T) + epsilon
    return meas.reshape(nobs, nmeas)
