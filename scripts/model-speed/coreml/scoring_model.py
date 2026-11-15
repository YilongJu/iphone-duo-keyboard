"""The scoring model of the Core ML route of docs/model-speed-design.md, in PyTorch.

One small decoder covers the four architectures of the shortlist: Llama (SmolLM2), Qwen2,
Qwen3 and the attention-only Granite 4.0. It loads the weights of the Hugging Face checkpoint
and keeps the keys and values of the tokens it read in two buffers, `key_cache` and
`value_cache`. coremltools turns the buffers into the state of a stateful Core ML model, so the
cache stays on the device between calls, as llama.cpp's cache does.

The model has two forms. They differ only in how a call writes the cache:
  flexible  (fixed_cells=False) for the processor and the GPU. The count of mask cells E
            changes from call to call. The call writes its keys and values into the cells
            E - Q to E - 1 and attends over the cells 0 to E - 1.
  fixed     (fixed_cells=True) for the Neural Engine, which needs shapes that stay the same
            within one shape of the model. E is always CACHE_CELLS. The input `write_cells`
            names the cell of each token, and a padding row has no cell and writes no cell.
            The scores of the vocabulary are made in parts of VOCABULARY_PART tokens, because
            the Neural Engine takes no axis longer than 16,384.

One call reads Q tokens and scores R of them:
  input_ids       [1, Q]        the tokens
  position_ids    [1, Q]        the position of each token for the rotary embedding
  attention_mask  [1, 1, Q, E]  0 where a token may attend to a cell, MASKED where it may not.
                  A mask of this shape lets the candidates of a request share the cells of the
                  context in one call: each candidate attends to the context and to its own
                  earlier tokens only.
  write_cells     [1, Q, E]     the fixed form only: 1 at the cell of each token, 0 elsewhere
  score_rows      [1, R]        the tokens of the call whose scores the caller wants
  target_ids      [1, R]        for each scored token, the token whose score the caller wants next
  first_ids       [1, F]        tokens whose scores the caller wants after the last scored token
It gives, for the scored tokens only:
  target_logit    [1, R]        the score of the target token after each scored token
  log_norm        [1, R]        the natural log of the sum of e to each score of the vocabulary
  space_log_mass  [1, R]        the same sum over the tokens whose text starts with a space
  first_logit     [1, F]        the score of each first token after the last scored token

So a log probability is target_logit - log_norm, and the space-after term is
space_log_mass - log_norm, the two numbers of LanguageModel/duo_lm_scorer.c. The window call
scores its last token only (R = 1), as the C scorer asks llama.cpp for the scores of the last
window token only, and its first_ids are the first tokens of the candidates.
"""

from __future__ import annotations

import json
import math
import pathlib

import torch
from safetensors.torch import load_file

# Room of the cache, as CONTEXT_SIZE of duo_lm_scorer.c.
CACHE_CELLS = 512
# A mask value that keeps a cell out of the attention in half precision.
MASKED = -30000.0
# The first tokens of a window call: one per candidate, as DUO_LM_MAX_CANDIDATES.
FIRST_TOKENS = 8
# The longest part of the vocabulary in one product of the fixed form.
VOCABULARY_PART = 16384
# The shapes of the fixed form: (Q, R), the tokens of a call and its scored tokens. Core ML
# matches the listed shapes of the inputs by their place in the list, and it refuses a model in
# which one input lists the same shape twice. So every Q and every R differs from the others.
# A window call scores one token and passes it R times; R grows with Q only to keep each R
# different. A candidate call scores every token, so R = Q. On the requests of the speed test a
# window call reads 5 tokens in the median and 68 at most, and a candidate call 17 in the median
# and 41 at most. A call takes the smallest shape of its kind that holds its tokens.
WINDOW_SHAPES = ((8, 1), (16, 2), (32, 3), (64, 4))
CANDIDATE_SHAPES = ((12, 12), (24, 24), (40, 40), (56, 56))
FIXED_SHAPES = WINDOW_SHAPES + CANDIDATE_SHAPES


class Settings:
    def __init__(self, config: dict):
        self.model_type = config["model_type"]
        if self.model_type not in ("llama", "qwen2", "qwen3", "granitemoehybrid"):
            raise ValueError(f"the architecture {self.model_type} is not one of the shortlist")
        if self.model_type == "granitemoehybrid":
            if any(kind != "attention" for kind in config["layer_types"]):
                raise ValueError("only the attention-only Granite 4.0 models are supported")
            if config["num_local_experts"] != 0:
                raise ValueError("only the Granite 4.0 models without experts are supported")
        self.hidden = config["hidden_size"]
        self.layers = config["num_hidden_layers"]
        self.heads = config["num_attention_heads"]
        self.kv_heads = config["num_key_value_heads"]
        self.head_dim = config.get("head_dim") or self.hidden // self.heads
        self.vocabulary = config["vocab_size"]
        self.eps = config["rms_norm_eps"]
        self.rope_theta = float(config["rope_theta"])
        if config.get("rope_scaling") is not None:
            raise ValueError("rope scaling is not supported")
        if not config.get("tie_word_embeddings", False):
            raise ValueError("only models with tied input and output embeddings are supported")
        granite = self.model_type == "granitemoehybrid"
        self.embedding_multiplier = float(config["embedding_multiplier"]) if granite else 1.0
        self.residual_multiplier = float(config["residual_multiplier"]) if granite else 1.0
        self.logits_scaling = float(config["logits_scaling"]) if granite else 1.0
        self.attention_scale = float(config["attention_multiplier"]) if granite else 1.0 / math.sqrt(self.head_dim)
        self.attention_bias = self.model_type == "qwen2"
        self.head_norms = self.model_type == "qwen3"


def rms_norm(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    variance = x.pow(2).mean(-1, keepdim=True)
    return x * torch.rsqrt(variance + eps) * weight


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    half = x.shape[-1] // 2
    return torch.cat((-x[..., half:], x[..., :half]), dim=-1)


class ScoringModel(torch.nn.Module):
    def __init__(self, folder: pathlib.Path, space_first: list[int], dtype: torch.dtype = torch.float32,
                 fixed_cells: bool = False):
        super().__init__()
        self.fixed_cells = fixed_cells
        config = json.loads(folder.joinpath("config.json").read_text())
        s = self.settings = Settings(config)
        weights = {name: tensor.to(dtype) for name, tensor in load_file(str(folder / "model.safetensors")).items()}
        self.embed = torch.nn.Parameter(weights["model.embed_tokens.weight"], requires_grad=False)
        self.final_norm = torch.nn.Parameter(weights["model.norm.weight"], requires_grad=False)
        self.blocks = []
        for layer in range(s.layers):
            p = f"model.layers.{layer}."
            block = {
                "attn_norm": weights[p + "input_layernorm.weight"],
                "mlp_norm": weights[p + "post_attention_layernorm.weight"],
                "q": weights[p + "self_attn.q_proj.weight"],
                "k": weights[p + "self_attn.k_proj.weight"],
                "v": weights[p + "self_attn.v_proj.weight"],
                "o": weights[p + "self_attn.o_proj.weight"],
            }
            if s.attention_bias:
                block["q_bias"] = weights[p + "self_attn.q_proj.bias"]
                block["k_bias"] = weights[p + "self_attn.k_proj.bias"]
                block["v_bias"] = weights[p + "self_attn.v_proj.bias"]
            if s.head_norms:
                block["q_norm"] = weights[p + "self_attn.q_norm.weight"]
                block["k_norm"] = weights[p + "self_attn.k_norm.weight"]
            if s.model_type == "granitemoehybrid":
                gate, up = weights[p + "shared_mlp.input_linear.weight"].chunk(2, dim=0)
                block["gate"], block["up"] = gate.contiguous(), up.contiguous()
                block["down"] = weights[p + "shared_mlp.output_linear.weight"]
            else:
                block["gate"] = weights[p + "mlp.gate_proj.weight"]
                block["up"] = weights[p + "mlp.up_proj.weight"]
                block["down"] = weights[p + "mlp.down_proj.weight"]
            for name, tensor in block.items():
                self.register_parameter(f"l{layer}_{name}", torch.nn.Parameter(tensor, requires_grad=False))
            self.blocks.append(list(block))
        # The rotary embedding as tables over the positions, so no angle is computed in half
        # precision: a position of 500 has a step of 0.25 in half precision.
        inverse = 1.0 / (s.rope_theta ** (torch.arange(0, s.head_dim, 2, dtype=torch.float64) / s.head_dim))
        angles = torch.arange(CACHE_CELLS, dtype=torch.float64)[:, None] * inverse[None, :]
        angles = torch.cat((angles, angles), dim=-1)
        self.register_buffer("cos_table", angles.cos().to(dtype), persistent=False)
        self.register_buffer("sin_table", angles.sin().to(dtype), persistent=False)
        self.register_buffer("space_ids", torch.tensor(space_first, dtype=torch.int32), persistent=False)
        # 0 for a token whose text starts with a space, MASKED for every other token.
        space_bias = torch.full((s.vocabulary,), MASKED, dtype=dtype)
        space_bias[torch.tensor(space_first, dtype=torch.long)] = 0
        self.register_buffer("space_bias", space_bias, persistent=False)
        cache_shape = (s.layers, 1, s.kv_heads, CACHE_CELLS, s.head_dim)
        self.register_buffer("key_cache", torch.zeros(cache_shape, dtype=torch.float16))
        self.register_buffer("value_cache", torch.zeros(cache_shape, dtype=torch.float16))

    def weight(self, layer: int, name: str) -> torch.Tensor:
        return getattr(self, f"l{layer}_{name}")

    def forward(self, input_ids, position_ids, attention_mask, *rest):
        """The flexible form takes score_rows, target_ids and first_ids after the mask. The
        fixed form takes write_cells first, then the same three."""
        if self.fixed_cells:
            write_cells, score_rows, target_ids, first_ids = rest
        else:
            score_rows, target_ids, first_ids = rest
        s = self.settings
        query_count = input_ids.shape[-1]
        end = attention_mask.shape[-1]
        start = end - query_count
        x = self.embed[input_ids[0]].unsqueeze(0) * s.embedding_multiplier
        cos = self.cos_table[position_ids[0]].unsqueeze(0).unsqueeze(0)
        sin = self.sin_table[position_ids[0]].unsqueeze(0).unsqueeze(0)
        mask = attention_mask.to(x.dtype)
        if self.fixed_cells:
            # [E, Q]: moves the keys of each token into its cell. A cell that no token of the
            # call writes keeps its old keys.
            placing = write_cells[0].transpose(0, 1).to(torch.float16)
            keeping = (1 - placing.sum(dim=-1, keepdim=True)).to(torch.float16)
        group = s.heads // s.kv_heads
        for layer in range(s.layers):
            w = lambda name: self.weight(layer, name)  # noqa: E731
            h = rms_norm(x, w("attn_norm"), s.eps)
            q = h @ w("q").T
            k = h @ w("k").T
            v = h @ w("v").T
            if s.attention_bias:
                q = q + w("q_bias")
                k = k + w("k_bias")
                v = v + w("v_bias")
            q = q.view(1, query_count, s.heads, s.head_dim).transpose(1, 2)
            k = k.view(1, query_count, s.kv_heads, s.head_dim).transpose(1, 2)
            v = v.view(1, query_count, s.kv_heads, s.head_dim).transpose(1, 2)
            if s.head_norms:
                q = rms_norm(q, w("q_norm"), s.eps)
                k = rms_norm(k, w("k_norm"), s.eps)
            q = q * cos + rotate_half(q) * sin
            k = k * cos + rotate_half(k) * sin
            if self.fixed_cells:
                old_keys = self.key_cache[layer : layer + 1]
                old_values = self.value_cache[layer : layer + 1]
                self.key_cache[layer : layer + 1] = old_keys * keeping + (placing @ k.to(torch.float16)).unsqueeze(0)
                self.value_cache[layer : layer + 1] = old_values * keeping + (placing @ v.to(torch.float16)).unsqueeze(0)
            else:
                self.key_cache[layer : layer + 1, :, :, start:end, :] = k.to(torch.float16).unsqueeze(0)
                self.value_cache[layer : layer + 1, :, :, start:end, :] = v.to(torch.float16).unsqueeze(0)
            keys = self.key_cache[layer, :, :, :end, :].to(x.dtype)
            values = self.value_cache[layer, :, :, :end, :].to(x.dtype)
            # Each key and value head serves `group` query heads in a row.
            keys = keys.unsqueeze(2).expand(1, s.kv_heads, group, end, s.head_dim).reshape(1, s.heads, end, s.head_dim)
            values = values.unsqueeze(2).expand(1, s.kv_heads, group, end, s.head_dim).reshape(1, s.heads, end, s.head_dim)
            weights = (q @ keys.transpose(-1, -2)) * s.attention_scale + mask
            weights = torch.softmax(weights.float(), dim=-1).to(x.dtype)
            attended = (weights @ values).transpose(1, 2).reshape(1, query_count, s.heads * s.head_dim)
            x = x + (attended @ w("o").T) * s.residual_multiplier
            h = rms_norm(x, w("mlp_norm"), s.eps)
            gated = torch.nn.functional.silu(h @ w("gate").T) * (h @ w("up").T)
            x = x + (gated @ w("down").T) * s.residual_multiplier
        # Only the scored tokens go through the final norm and the scores of the vocabulary.
        x = x.index_select(1, score_rows[0].long())
        x = rms_norm(x, self.final_norm, s.eps)
        target_logit = (x * self.embed[target_ids[0].long()].unsqueeze(0)).sum(-1).float() / s.logits_scaling
        first_logit = (x[:, -1, :] @ self.embed[first_ids[0].long()].T).float() / s.logits_scaling
        if self.fixed_cells:
            norms, spaces = [], []
            for begin in range(0, s.vocabulary, VOCABULARY_PART):
                stop = min(begin + VOCABULARY_PART, s.vocabulary)
                part = (x @ self.embed[begin:stop].T).float() / s.logits_scaling
                norms.append(torch.logsumexp(part, dim=-1))
                spaces.append(torch.logsumexp(part + self.space_bias[begin:stop].float(), dim=-1))
            log_norm = torch.logsumexp(torch.stack(norms, dim=-1), dim=-1)
            space_log_mass = torch.logsumexp(torch.stack(spaces, dim=-1), dim=-1)
        else:
            logits = (x @ self.embed.T).float() / s.logits_scaling
            log_norm = torch.logsumexp(logits, dim=-1)
            space_log_mass = torch.logsumexp(logits.index_select(-1, self.space_ids.long()), dim=-1)
        return target_logit, log_norm, space_log_mass, first_logit


def space_first_tokens(folder: pathlib.Path) -> list[int]:
    """The tokens whose text starts with a space, as duo_lm_scorer.c finds them.

    The four tokenizers are byte-level BPE vocabularies, where the byte of a space is the
    character "Ġ". The scorer reads at most 64 bytes of a token's text, and a control token
    gives no text there, so neither counts.
    """
    tokenizer = json.loads(folder.joinpath("tokenizer.json").read_text(encoding="utf-8"))
    model = tokenizer["model"]
    if model["type"] != "BPE":
        raise ValueError(f"the tokenizer is {model['type']}, and only byte-level BPE is supported")
    special = {entry["id"] for entry in tokenizer.get("added_tokens", []) if entry.get("special")}
    byte_of = byte_decoder()
    found = []
    for text, token in model["vocab"].items():
        if token in special:
            continue
        data = bytes(byte_of[character] for character in text)
        if 0 < len(data) <= 64 and data[0] == 0x20:
            found.append(token)
    for entry in tokenizer.get("added_tokens", []):
        content = entry["content"].encode("utf-8")
        if not entry.get("special") and 0 < len(content) <= 64 and content[0] == 0x20:
            found.append(entry["id"])
    return sorted(set(found))


def byte_decoder() -> dict[str, int]:
    """The map of GPT-2 from the characters of a byte-level BPE vocabulary to the bytes."""
    printable = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1))
    printable += list(range(ord("®"), ord("ÿ") + 1))
    characters = printable[:]
    extra = 0
    for byte in range(256):
        if byte not in printable:
            printable.append(byte)
            characters.append(256 + extra)
            extra += 1
    return {chr(character): byte for byte, character in zip(printable, characters)}
