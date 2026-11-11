"""Weight edits of a small language model for the English re-ranker.

Every edit starts from the stock weights theta_0 and one or more fine-tuned weights theta_i of
the same architecture. A task vector is tau_i = theta_i - theta_0 (Ilharco et al. 2023). The
functions below return a new state dict and never change their inputs.

- scaled_task_vector: theta_0 + lam * tau. lam in [0, 1] is the linear weight interpolation of
  WiSE-FT (Wortsman et al. 2022); lam > 1 extrapolates the task vector.
- task_arithmetic: theta_0 + lam * sum_i tau_i (Ilharco et al. 2023).
- uniform_soup: the mean of the fine-tuned weights (Wortsman et al. 2022, uniform soup).
- ties: trim each tau_i to its top k fraction by magnitude, elect a sign per weight by the sign of
  the summed trimmed values, and take the mean of the trimmed values that agree with that sign
  (Yadav et al. 2023), then theta_0 + lam * merged.
- dare: drop each weight of tau_i with probability p and scale the rest by 1 / (1 - p)
  (Yu et al. 2024), then task arithmetic over the results.
- random_like: a random direction with the Frobenius norm of tau, tensor by tensor, as a control.
- add_attention_output_bias: fold a constant residual-stream vector into the attention output
  bias of one block (contrastive activation addition, Rimsky et al. 2024, as a weight edit).
"""
import torch


def task_vector(base: dict, tuned: dict) -> dict:
    if base.keys() != tuned.keys():
        raise SystemExit(f"the two state dicts hold different tensors: {sorted(base.keys() ^ tuned.keys())[:5]}")
    vector = {}
    for name, value in base.items():
        if value.shape != tuned[name].shape:
            raise SystemExit(f"{name}: shape {tuple(value.shape)} against {tuple(tuned[name].shape)}")
        vector[name] = tuned[name].float() - value.float()
    return vector


def apply(base: dict, vector: dict, lam: float) -> dict:
    return {name: value.float() + lam * vector[name] for name, value in base.items()}


def scaled_task_vector(base: dict, tuned: dict, lam: float) -> dict:
    return apply(base, task_vector(base, tuned), lam)


def task_arithmetic(base: dict, tuned_list: list[dict], lam: float) -> dict:
    vectors = [task_vector(base, tuned) for tuned in tuned_list]
    summed = {name: sum(v[name] for v in vectors) for name in base}
    return apply(base, summed, lam)


def uniform_soup(tuned_list: list[dict]) -> dict:
    names = tuned_list[0].keys()
    return {name: sum(t[name].float() for t in tuned_list) / len(tuned_list) for name in names}


def flatten(vector: dict, names: list[str]) -> torch.Tensor:
    return torch.cat([vector[name].flatten() for name in names])


def unflatten(flat: torch.Tensor, like: dict, names: list[str]) -> dict:
    result, start = {}, 0
    for name in names:
        count = like[name].numel()
        result[name] = flat[start:start + count].view_as(like[name]).clone()
        start += count
    return result


def ties(base: dict, tuned_list: list[dict], keep: float, lam: float) -> dict:
    """TIES-merging as the authors' code does it (prateeky2806/ties-merging, merge_utils.py):
    each task vector is flattened over the whole model and keeps its top `keep` fraction by
    magnitude; the elected sign of a weight is the sign of the summed trimmed values, and a zero
    sum takes the majority sign; the merge is the mean of the values that agree with it."""
    names = sorted(base)
    rows = []
    for tuned in tuned_list:
        flat = flatten(task_vector(base, tuned), names)
        kept = int(flat.numel() * keep)
        threshold = flat.abs().kthvalue(flat.numel() - kept + 1).values
        rows.append(torch.where(flat.abs() >= threshold, flat, torch.zeros_like(flat)))
    stack = torch.stack(rows)
    sign = torch.sign(stack.sum(0))
    sign[sign == 0] = torch.sign(sign.sum())
    agree = torch.where(sign > 0, stack > 0, stack < 0)
    merged = (stack * agree).sum(0) / agree.sum(0).clamp(min=1)
    return apply(base, unflatten(merged, base, names), lam)


def tftv_update(weight: torch.Tensor, steering: torch.Tensor, mean_input: torch.Tensor) -> torch.Tensor:
    """The rank-one update of Training-Free Task Vectors (Perin et al. 2026, arXiv 2609.09054,
    section 3.2) for a module y = W x with W of shape (out, in) that writes to the residual
    stream: s_bar q^T, with s_bar = s / |s| and q = sum_i sign(mu^T v_i) sigma_i v_i over the SVD
    W = sum_i sigma_i u_i v_i^T, sign(0) = 1. Its Frobenius norm equals that of W."""
    _, sigma, vh = torch.linalg.svd(weight.double(), full_matrices=False)
    signs = torch.sign(vh @ mean_input.double())
    signs[signs == 0] = 1
    q = (signs * sigma) @ vh
    direction = steering.double() / steering.double().norm()
    return torch.outer(direction, q).to(weight.dtype)


def dare(base: dict, tuned_list: list[dict], drop: float, lam: float, seed: int) -> dict:
    generator = torch.Generator().manual_seed(seed)
    summed = {name: torch.zeros_like(value, dtype=torch.float32) for name, value in base.items()}
    for tuned in tuned_list:
        for name, value in task_vector(base, tuned).items():
            keep = torch.rand(value.shape, generator=generator) >= drop
            summed[name] += value * keep / (1.0 - drop)
    return apply(base, summed, lam)


def random_like(vector: dict, seed: int) -> dict:
    """A Gaussian direction with the Frobenius norm of each tensor of `vector`. A tensor that the
    fine-tune left unchanged stays unchanged."""
    generator = torch.Generator().manual_seed(seed)
    result = {}
    for name, value in vector.items():
        norm = float(value.norm())
        noise = torch.randn(value.shape, generator=generator)
        result[name] = noise * (norm / float(noise.norm())) if norm > 0 else torch.zeros_like(value)
    return result


def norms(vector: dict) -> dict:
    total = sum(float(v.norm()) ** 2 for v in vector.values()) ** 0.5
    changed = sum(v.numel() for v in vector.values() if bool(v.abs().max() > 0))
    return {"frobenius": total, "changed_weights": changed, "all_weights": sum(v.numel() for v in vector.values())}
