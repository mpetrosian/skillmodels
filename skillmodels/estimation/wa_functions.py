"""Contains functions that are needed for the WA estimator."""

import numpy as np
import pandas as pd
import skillmodels.model_functions.transition_functions as tf
from patsy import dmatrix


def loadings_from_covs(data, normalization):
    """Factor loadings of measurements of one factor in the first.

    Calculate the factor loadings of all measurements of one factor in the
    first period as average of ratios of covariances. For this to be possible,
    at least three  measurement variables have to be available in the dataset.

    Args:
        data (DataFrame): pandas DataFrame with the measurement data for one
            factor in one period.
        normalization (list): The first value is the name of a normalized
            measurement, the second is the value it is normalized to.

    Returns:
        loadings (Series): pandas Series with estimated factor loadings

    """
    measurements = list(data.columns)
    nmeas = len(measurements)
    assert nmeas >= 3, (
        'For covariance based factor loading estimation 3 or more '
        'measurements are needed.')

    cov = data.cov()
    load_norm, load_norm_val = normalization
    loadings = pd.Series(index=measurements, name='loadings')

    for m in measurements:
        if m != load_norm:
            estimates = []
            for m_prime in measurements:
                if m_prime not in [m, load_norm]:
                    nominator = load_norm_val * cov.loc[m, m_prime]
                    denominator = cov.loc[load_norm, m_prime]
                    estimates.append(nominator / denominator)
            loadings[m] = np.mean(estimates)
        else:
            loadings[m] = load_norm_val
    return loadings


def intercepts_from_means(data, normalization, loadings):
    """Calculate intercepts and factor means for 1 factor in the first period.

    If the normalization list is not empty, it is assumed that the factor
    mean is not normalized and has to be estimated. In this case, the factor
    mean is calculated first and appended to the mean_list. Later the
    non-normalized intercepts are calculated and stored in storage_df.

    Args:
        data (DataFrame): pandas DataFrame with the measurement data for one
            factor in one period.
        normalization (list): The first value is the name of a normalized
            measurement, the second is the value it is normalized to.
        loadings (Series): pandas Series with estimated factor loadings

    Returns:
        intercepts (Series): pandas Series with estimated measurement
        intercepts

    Returns:
        factor mean: The estimated factor mean if a intercept was normalized
        or None
    """
    measurements = list(data.columns)

    if len(normalization) == 0:
        intercepts = data.mean()
        factor_mean = None
    else:
        intercepts = pd.Series(index=measurements, name='intercepts')
        intercept_norm, intercept_norm_val = normalization
        loading = loadings[intercept_norm]
        factor_mean = \
            (data[intercept_norm].mean() - intercept_norm_val) / loading

        for m, meas in enumerate(measurements):
            if meas != intercept_norm:
                loading = loadings[meas]
                intercepts[meas] = \
                    data[meas].mean() - loading * factor_mean
            else:
                intercepts[meas] = intercept_norm_val
    return intercepts, factor_mean


def prepend_index_level(df, to_prepend):
    df = df.copy()
    df.index = pd.MultiIndex.from_tuples(
        [(to_prepend, x) for x in df.index])
    return df


def prepend_column_level(df, to_prepend):
    df = df.copy()
    df.columns = pd.MultiIndex.from_tuples(
        [(to_prepend, x) for x in df.columns])
    return df


def initial_meas_coeffs(y_data, measurements, normalizations):
    """Dataframe of loadings and intercepts for all factors in initial period.

    Args:
        y_data (DataFrame): pandas DataFrame with measurement data of initial
            period.
        measurements (dictionary): the keys are the factors. The values are
            nested lits with one sublist of measurement names for each period.
        normalizations (dictionary): the keys are the factors. the values are
            dictionaries with 'intercepts' and 'loadings' as keys. Their values
            are lists of lists with one sublist for each period. Each sublist
            contains the name of the normalized measurements as first entry and
            the value to which it is normalized as second entry.

    Returns:
        meas_coeffs (DataFrame): DataFrame with loadings and intercepts of the
        initial period.

    Returns:
        X_zero (np.ndarray): numpy array with initial factor means.

    """
    factors = sorted(list(measurements.keys()))
    to_concat = []
    X_zero = []
    for f, factor in enumerate(factors):
        meas_list = measurements[factor][0]
        data = y_data[meas_list]
        norminfo_load = normalizations[factor]['loadings'][0]

        loadings = loadings_from_covs(data, norminfo_load)
        norminfo_intercept = normalizations[factor]['intercepts'][0]
        intercepts, factor_mean = intercepts_from_means(
            data, norminfo_intercept, loadings)
        to_concat.append(pd.concat([loadings, intercepts], axis=1))
        X_zero.append(factor_mean)

    meas_coeffs = pd.concat(to_concat)
    return meas_coeffs, np.array(X_zero)


def factor_covs_and_measurement_error_variances(
        meas_cov, loadings, meas_per_factor):
    """Covs of latent factors and vars of measurement equations in a period.

    Args:
        meas_cov (DataFrame): covariance matrix of measurement data.
        loadings (Series): factor loadings
        meas_per_factor (dictionary): the keys are the factors. The values are
            a list with the names of their measurements.

    Returns:
        factor_covs (np.ndarray): 1d array with the upper triangular
        elements of the covariance matrix of the latent factors.

    Returns:
        meas_error_variances (Series): variances of errors in measurement
        equations.

    """
    factors = sorted(list(meas_per_factor.keys()))

    scaled_meas_cov = meas_cov.divide(
        loadings, axis=0).divide(loadings, axis=1)

    diag_bool = np.eye(len(scaled_meas_cov), dtype=bool)
    diag_data = scaled_meas_cov.copy(deep=True).values[diag_bool]
    diag_series = pd.Series(
        data=diag_data, index=scaled_meas_cov.index,
        name='meas_error_variances')
    scaled_meas_cov.values[diag_bool] = np.nan
    # print('\n\nrelevant_parts_of_cov_matrix\n')
    factor_covs = []
    for f1, factor1 in enumerate(factors):
        meas_list1 = meas_per_factor[factor1]
        for f2, factor2 in enumerate(factors):
            meas_list2 = meas_per_factor[factor2]
            if f2 >= f1:
                relevant = scaled_meas_cov.loc[meas_list1, meas_list2]
                # print(relevant)
                cov_estimate = relevant.mean().mean()
                factor_covs.append(cov_estimate)
                if f2 == f1:
                    diag_series[meas_list1] -= cov_estimate

    factor_covs = np.array(factor_covs)
    meas_error_variances = diag_series
    meas_error_variances *= loadings ** 2

    return factor_covs, meas_error_variances


def iv_reg_array_dict(depvar_name, indepvar_names, instrument_names,
                      transition_name, data):
    """Prepare the data arrays for an iv regression.

    Args:
        data (DataFrame): contains all variables that are used. Can contain any
            number of additional variables without causing problems.
        depvar_name (str): the name of the dependent variable
        indepvar_names (list): list of strings with the names of the
            independent variables.
        indepvar_names (list): list of strings with the names of the
            instruments
        transition_name (str): name of the transition function that is
            estimated via the iv approach of the wa estimator.

    Returns:
        arr_dict (dict): A dictionary with the keys depvar_arr, indepvars_arr
        and instruments_arr. The corresponding values are numpy arrays
        with the data for an iv regression. NaNs are removed.

    """
    arr_dict = {}
    used_variables = \
        [('y', depvar_name)] + [('x', indep) for indep in indepvar_names] + \
        [('z', instr) for sublist in instrument_names for instr in sublist]

    data = data[used_variables].dropna()
    for category in ['x', 'z']:
        data[(category, 'constant')] = 1.0

    arr_dict['depvar_arr'] = data[('y', depvar_name)].values

    formula_func = getattr(tf, 'iv_formula_{}'.format(transition_name))
    indep_formula, instr_formula = formula_func(
        indepvar_names, instrument_names)
    arr_dict['indepvars_arr'] = \
        dmatrix(indep_formula, data=data['x'], return_type='dataframe').values
    arr_dict['instruments_arr'] = \
        dmatrix(instr_formula, data=data['z'], return_type='dataframe').values

    arr_dict['non_missing_index'] = data.index
    return arr_dict


def iv_reg(depvar_arr, indepvars_arr, instruments_arr, fit_method='2sls'):
    """Estimate a linear-in-parameters instrumental variable equation via GMM.

    All input arrays must not contain NaNs and constants must be included
    explicitly in indepvars and instruments.

    args:
        depvar (np.ndarray): array of length n, dependent variable.
        indepvars (np.ndarray): array of shape [n, k], independent variables
        instruments (np.ndarray): array of shape [n, >=k]. Instruments
            have to include exogenous variables that are already in indepvars.
        fit_method (str): takes the values '2sls' or 'optimal'. 'Optimal' is
            computationally  expensive but uses a more efficient weight matrix.
            The default is '2sls'.

    Returns:
        beta (np.ndarray): array of length k with the estimated parameters.

    """
    y = depvar_arr
    x = indepvars_arr
    z = instruments_arr

    nobs, k_prime = z.shape
    w = _iv_gmm_weights(z)
    beta = _iv_math(y, x, z, w)

    if fit_method == 'optimal':
        u = y - np.dot(x, beta)
        w = _iv_gmm_weights(z, u)
        beta = _iv_math(y, x, z, w)

    return beta


def _iv_math(y, x, z, w):
    xTz = x.T.dot(z)
    helper = xTz.dot(w)
    try:
        inverse_part = np.linalg.pinv(np.dot(helper, xTz.T))
    except:
        print('non_invertible_matrix:\n', np.dot(helper, xTz.T))
        print('z_matrix:\n', z)
        print('helper:\n', helper)
    y_part = helper.dot(z.T.dot(y))
    beta = inverse_part.dot(y_part)

    return beta


def _iv_gmm_weights(z, u=None):
    nobs, k_prime = z.shape
    if u is None:
        try:
            w = np.linalg.pinv(np.dot(z.T, z) / nobs)
        except:
            print('non_invertible_matrix:\n', np.dot(z.T, z) / nobs)
            print('z_matrix:\n', z)
    else:
        u_squared = u ** 2
        outerprod = z.reshape(nobs, 1, k_prime) * z.reshape(nobs, k_prime, 1)
        s = (u_squared.reshape(nobs, 1, 1) * outerprod).sum(axis=0) / nobs
        w = np.linalg.pinv(s)
    return w


def large_df_for_iv_equations(depvar_data, indepvars_data, instruments_data):
    to_concat = [prepend_column_level(depvar_data, 'y'),
                 prepend_column_level(indepvars_data, 'x'),
                 prepend_column_level(instruments_data, 'z')]

    df = pd.concat(to_concat, axis=1)
    return df


def transition_error_variance_from_u_covs(u_covs, loadings):

    scaled_u_covs = u_covs.divide(loadings, level=0, axis=0).divide(loadings)
    transition_error_variance = scaled_u_covs.mean().mean()
    return transition_error_variance


def anchoring_error_variance_from_u_vars(
        u_vars, indepvars_permutations, anch_loadings, meas_loadings,
        anchored_factors):

    meas_noise_df = pd.DataFrame(0.0, index=u_vars.index,
                                 columns=anchored_factors)

    for p, perm in enumerate(indepvars_permutations):
        for f, factor in enumerate(anchored_factors):
            meas_name = perm[f][:-6]
            m_loading_squared = meas_loadings[meas_name] ** 2
            meas_noise_df.loc[p, factor] = u_vars[p] / m_loading_squared
    anch_loadings_squared = anch_loadings ** 2
    meas_noise_df *= anch_loadings_squared
    anch_variance_estimates = u_vars - meas_noise_df.sum(axis=1)
    anch_variance = anch_variance_estimates.mean()
    return anch_variance
