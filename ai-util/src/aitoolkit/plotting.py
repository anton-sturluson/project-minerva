"""Library of plotting functions."""
import seaborn as sns


def plot_boxplot(x, y, data, ax=None):
    """Plot boxplot with mean and median."""
    ax = sns.boxplot(
        x=x,
        y=y,
        data=data,
        ax=ax,
        showfliers=False,
        medianprops={
            "color": "red"
        },
        showmeans=True,
        meanprops={
            "marker": "x",
            "markeredgecolor": "black",
            "markersize": "5"
        }
    )
    return ax
