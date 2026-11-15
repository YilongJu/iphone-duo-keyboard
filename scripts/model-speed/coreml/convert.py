"""Converts one model of the shortlist into a stateful Core ML model with coremltools.

Usage: python convert.py HF_FOLDER OUT.mlpackage --weights fp16|int4
  fp16  16-bit weights
  int4  4-bit weights, symmetric, in blocks of 32 values, the nearest Core ML form to the Q4 files
        of llama.cpp. Core ML on iOS 18 and later reads such weights without first unpacking them.

The model is the one of scoring_model.py. Its inputs and outputs are named there. The number of
tokens of a call (Q) may be 1 to 288 and the cells of the attention mask (E) 1 to 512, so one
model serves the window call and the candidate call. A model with shapes that change runs on
the processor or the GPU. The Neural Engine needs fixed shapes, so this model does not reach it.
"""

import argparse
import pathlib
import sys

import coremltools as ct
import numpy as np
import torch

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from scoring_model import CACHE_CELLS, ScoringModel, space_first_tokens  # noqa: E402

MAX_CALL_TOKENS = 288


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("out")
    parser.add_argument("--weights", choices=("fp16", "int4"), required=True)
    arguments = parser.parse_args()
    folder = pathlib.Path(arguments.folder)
    model = ScoringModel(folder, space_first_tokens(folder)).eval()
    settings = model.settings

    # The example of the trace: a call of 3 tokens after 2 cached ones.
    ids = torch.tensor([[1, 2, 3]], dtype=torch.int32)
    positions = torch.tensor([[2, 3, 4]], dtype=torch.int32)
    mask = torch.zeros((1, 1, 3, 5), dtype=torch.float32)
    targets = torch.zeros((1, 3), dtype=torch.int32)
    with torch.no_grad():
        traced = torch.jit.trace(model, (ids, positions, mask, targets))

    query = ct.RangeDim(lower_bound=1, upper_bound=MAX_CALL_TOKENS, default=3)
    cells = ct.RangeDim(lower_bound=1, upper_bound=CACHE_CELLS, default=5)
    cache_shape = (settings.layers, 1, settings.kv_heads, CACHE_CELLS, settings.head_dim)
    mlmodel = ct.convert(
        traced,
        inputs=[
            ct.TensorType(name="input_ids", shape=(1, query), dtype=np.int32),
            ct.TensorType(name="position_ids", shape=(1, query), dtype=np.int32),
            ct.TensorType(name="attention_mask", shape=(1, 1, query, cells), dtype=np.float16),
            ct.TensorType(name="target_ids", shape=(1, query), dtype=np.int32),
        ],
        outputs=[
            ct.TensorType(name="last_logits", dtype=np.float32),
            ct.TensorType(name="target_logit", dtype=np.float32),
            ct.TensorType(name="log_norm", dtype=np.float32),
            ct.TensorType(name="space_log_mass", dtype=np.float32),
        ],
        states=[
            ct.StateType(wrapped_type=ct.TensorType(shape=cache_shape, dtype=np.float16), name="key_cache"),
            ct.StateType(wrapped_type=ct.TensorType(shape=cache_shape, dtype=np.float16), name="value_cache"),
        ],
        minimum_deployment_target=ct.target.iOS18,
        compute_precision=ct.precision.FLOAT16,
        skip_model_load=True,
    )
    if arguments.weights == "int4":
        # A block of 32 zeros has a scale of 0, and the quantizer divides by it. The table of the
        # sine of the rotary embedding starts with a row of zeros, so such tables keep 16 bits.
        kept = {}
        for op in mlmodel._mil_program.functions["main"].operations:
            if op.op_type != "const" or op.val.val is None:
                continue
            value = np.asarray(op.val.val)
            if value.size < 2048 or value.ndim != 2 or value.shape[-1] % 32 != 0 or value.dtype.kind != "f":
                continue
            if (np.abs(value.reshape(value.shape[0], -1, 32)).max(axis=-1) == 0).any():
                kept[op.name] = None
                print(f"keeps 16 bits: {op.name} {value.shape}")
        config = ct.optimize.coreml.OptimizationConfig(
            global_config=ct.optimize.coreml.OpLinearQuantizerConfig(
                mode="linear_symmetric", dtype="int4", granularity="per_block", block_size=32),
            op_name_configs=kept)
        mlmodel = ct.optimize.coreml.linear_quantize_weights(mlmodel, config=config)
    mlmodel.short_description = f"Scoring model of {folder.name} for the speed test of Duo Keyboard, {arguments.weights} weights"
    mlmodel.save(arguments.out)
    print(f"saved {arguments.out}")


if __name__ == "__main__":
    main()
