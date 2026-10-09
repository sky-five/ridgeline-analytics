"""Support ticket themes: a small text classifier trained on a hand-labelled sample.

300 tickets were labelled by Claude Code from the ticket text (seed: ticket_theme_labels).
80% train a TF-IDF + logistic regression model, 20% are held out to measure accuracy
(singular test: assert_ticket_theme_holdout_accuracy). Every other ticket gets the model's prediction.
"""
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline


def _to_pandas(relation) -> pd.DataFrame:
    """DuckDB gives a relation with .df(); Snowflake gives a Snowpark DataFrame with UPPERCASE columns."""
    df = relation.to_pandas() if hasattr(relation, "to_pandas") else relation.df()
    return df.rename(columns=str.lower)


def model(dbt, session):
    dbt.config(materialized="table", packages=["pyarrow", "scikit-learn", "pandas", "numpy"])
    tickets_rel = dbt.ref("stg_support__tickets")
    on_snowflake = hasattr(tickets_rel, "to_pandas")
    tickets = _to_pandas(tickets_rel)[["ticket_id", "subject", "body"]]
    labels = _to_pandas(dbt.ref("ticket_theme_labels"))[["ticket_id", "theme"]]

    df = tickets.merge(labels.rename(columns={"theme": "labelled_theme"}), on="ticket_id", how="left")
    df["text"] = df.subject.fillna("") + ". " + df.body.fillna("")

    labelled = df.labelled_theme.notna()
    # deterministic 80/20 split of the labelled sample
    rng = np.random.default_rng(7)
    holdout_ids = set(rng.choice(df.loc[labelled, "ticket_id"].sort_values().to_numpy(),
                                 size=int(labelled.sum() * 0.2), replace=False))
    df["split"] = np.where(~labelled, "unlabelled",
                           np.where(df.ticket_id.isin(holdout_ids), "holdout", "train"))

    train = df[df.split == "train"]
    clf = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True),
                        LogisticRegression(max_iter=2000, C=5.0))
    clf.fit(train.text, train.labelled_theme)
    proba = clf.predict_proba(df.text)
    df["predicted_theme"] = clf.classes_[proba.argmax(axis=1)]
    df["confidence"] = proba.max(axis=1)
    df["churn_theme"] = df.labelled_theme.where(labelled, df.predicted_theme)

    out = df[["ticket_id", "churn_theme", "predicted_theme", "labelled_theme", "confidence", "split"]]
    return out.rename(columns=str.upper) if on_snowflake else out
