"""Detection metrics. auc / tpr_at_fpr copied from the benchmark harness (benchmark/harness/summarize.py)."""


def auc(fake_scores, real_scores):
    if not fake_scores or not real_scores: return float("nan")
    ranked = sorted([(s, 1) for s in fake_scores] + [(s, 0) for s in real_scores])
    rank_sum, index = 0.0, 0
    while index < len(ranked):  # average ranks over ties
        end = index
        while end + 1 < len(ranked) and ranked[end + 1][0] == ranked[index][0]: end += 1
        average_rank = (index + end) / 2 + 1
        rank_sum += sum(average_rank for k in range(index, end + 1) if ranked[k][1] == 1)
        index = end + 1
    n_fake, n_real = len(fake_scores), len(real_scores)
    return (rank_sum - n_fake * (n_fake + 1) / 2) / (n_fake * n_real)


def tpr_at_fpr(fake_scores, real_scores, target_fpr):
    if not fake_scores or not real_scores: return float("nan")
    threshold = sorted(real_scores, reverse=True)[min(len(real_scores) - 1, int(target_fpr * len(real_scores)))]
    return sum(s > threshold for s in fake_scores) / len(fake_scores)


def detection_metrics(fake_scores, real_scores) -> dict:
    return {"n_fake": len(fake_scores), "n_real": len(real_scores), "auc": auc(fake_scores, real_scores),
            "tpr@1%fpr": tpr_at_fpr(fake_scores, real_scores, 0.01), "tpr@5%fpr": tpr_at_fpr(fake_scores, real_scores, 0.05)}


def mean(values):
    values = [v for v in values if v == v]
    return sum(values) / len(values) if values else float("nan")
