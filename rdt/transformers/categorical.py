import numpy as np
import pandas as pd
from faker import Faker
from scipy.stats import norm

from rdt.transformers.base import BaseTransformer

MAPS = {}


class CategoricalTransformer(BaseTransformer):
    """Transformer for categorical data.

    This transformer computes a float representative for each one of the categories
    found in the fit data, and then replaces the instances of these categories with
    the corresponding representative.

    The representatives are decided by sorting the categorical values by their relative
    frequency, then dividing the ``[0, 1]`` interval by these relative frequencies, and
    finally assigning the middle point of each interval to the corresponding category.

    When the transformation is reverted, each value is assigned the category that
    corresponds to the interval it falls int.

    Null values are considered just another category.

    Args:
        anonymize (str, tuple or list):
            Anonymization category. ``None`` disables anonymization. Defaults to ``None``.
    """

    mapping = None
    intervals = None

    def __init__(self, anonymize=False, add_noise=False, clip=False):
        self.anonymize = anonymize
        self.add_noise = add_noise
        self.clip = clip

    def _get_faker(self):
        """Return the faker object to anonymize data.

        Returns:
            function:
                Faker function to generate new data instances with ``self.anonymize`` arguments.

        Raises:
            ValueError:
                A ``ValueError`` is raised if the faker category we want don't exist.
        """

        if isinstance(self.anonymize, (tuple, list)):
            category, *args = self.anonymize
        else:
            category = self.anonymize
            args = tuple()

        try:
            faker_method = getattr(Faker(), category)

            def faker():
                return faker_method(*args)

            return faker
        except AttributeError:
            raise ValueError('Category "{}" couldn\'t be found on faker'.format(self.anonymize))

    def _anonymize(self, data):
        """Anonymize data and save in-memory the anonymized label encoding."""
        faker = self._get_faker()
        uniques = data.unique()
        fake_data = [faker() for x in range(len(uniques))]

        mapping = dict(zip(uniques, fake_data))
        MAPS[id(self)] = mapping

        return data.map(mapping)

    @staticmethod
    def _get_intervals(data):
        """Compute intervals for each categorical value.

        Args:
            data (pandas.Series):
                Data to analyze.

        Returns:
            dict:
                intervals for each categorical value (start, end).
        """
        frequencies = data.value_counts(dropna=False).reset_index()

        # Sort also by index to make sure that results are always the same
        name = data.name or 0
        sorted_freqs = frequencies.sort_values([name, 'index'], ascending=False)
        frequencies = sorted_freqs.set_index('index', drop=True)[name]

        start = 0
        end = 0
        elements = len(data)

        intervals = dict()
        for value, frequency in frequencies.items():
            prob = frequency / elements
            end = start + prob
            mean = (start + end) / 2
            std = prob / 6
            intervals[value] = (start, end, mean, std)
            start = end

        return intervals

    def fit(self, data):
        """Fit the transformer to the data.

        Create the mapping dict to save the label encoding, anonymizing the data
        before if needed.
        Finaly, compute the intervals for each categorical value.

        Args:
            data (pandas.Series or numpy.ndarray):
                Data to fit the transformer to.
        """
        self.mapping = dict()

        if isinstance(data, np.ndarray):
            data = pd.Series(data)

        if self.anonymize:
            data = self._anonymize(data)

        self.intervals = self._get_intervals(data)

    def _get_value(self, category):
        """Get the value that represents this category"""
        mean, std = self.intervals[category][2:]
        if self.add_noise:
            return norm.rvs(mean, std)
        else:
            return mean

    def transform(self, data):
        """Transform categorical values to float values.

        If anonymization is required, replace the values with the corresponding
        anonymized counterparts before transforming.

        Then replace the categories with their float representative value.

        Args:
            data (pandas.Series or numpy.ndarray):
                Data to transform.

        Returns:
            numpy.ndarray:
        """
        if not isinstance(data, pd.Series):
            data = pd.Series(data)

        if self.anonymize:
            data = data.map(MAPS[id(self)])

        if len(self.intervals) == 2:
            category = list(self.intervals.values())[0]
            return (data == category).astype(int)

        return data.fillna(np.nan).apply(self._get_value).values

    def _normalize(self, data):
        """Normalize data to the range [0, 1].

        This is done by substracting to each value its integer part, leaving only
        the decimal part, and then shifting the sign of the negative values.
        """
        if self.clip:
            return data.clip(0, 1)

        data = data - data.astype(int)
        data[data < 0] = -data[data < 0]
        return data

    def reverse_transform(self, data):
        """Convert float values back to the original categorical values.

        Args:
            data (numpy.ndarray):
                Data to revert.

        Returns:
            pandas.Series
        """
        if not isinstance(data, pd.Series):
            if len(data.shape) > 1:
                data = data[:, 0]

            data = pd.Series(data)

        data = self._normalize(data)

        result = pd.Series(index=data.index)

        for category, values in self.intervals.items():
            start, end = values[:2]
            result[(start < data) & (data < end)] = category

        return result


class OneHotTransformer(BaseTransformer):

    def fit(self, data):
        self.dummies = pd.Series(data.value_counts().index)

    def transform(self, data):
        dummies = pd.get_dummies(data)
        return dummies.reindex(columns=self.dummies, fill_value=0).values.astype(int)

    def reverse_transform(self, data):
        indices = np.argmax(data, axis=1)
        return pd.Series(indices).map(self.dummies)
