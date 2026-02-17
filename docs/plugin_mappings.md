# Plugin Parameter Mappings

## SSL Native Channel Strip / E-Channel

### EQ Bands
| Band | Freq Key | Gain Key | Q Key | Type |
|------|----------|----------|-------|------|
| LF | LF Freq | LF Gain | - | Low Shelf |
| LMF | LMF Freq | LMF Gain | LMF Q | Peak |
| HMF | HMF Freq | HMF Gain | HMF Q | Peak |
| HF | HF Freq | HF Gain | - | High Shelf |

### Compressor
| Parameter | Keys |
|-----------|------|
| Threshold | Comp Threshold, CompThresh |
| Ratio | Comp Ratio, CompRatio |
| Attack | Comp Attack, CompAttack |
| Release | Comp Release, CompRelease |

## Waves CLA-76

| Parameter | Keys |
|-----------|------|
| Input | Input, input |
| Output | Output, output |
| Attack | Attack, attack |
| Release | Release, release |
| Ratio | Ratio, ratio |

## Waves CLA-2A

| Parameter | Keys |
|-----------|------|
| Peak Reduction | Peak Reduction, PeakReduction |
| Output Gain | Output Gain, Gain |

## FabFilter Pro-Q 3

Band parameters follow pattern: `Band {N} {Param}`

| Parameter | Pattern |
|-----------|---------|
| Frequency | Band {N} Freq, Band {N} Frequency |
| Gain | Band {N} Gain |
| Q | Band {N} Q |
| Shape | Band {N} Shape (0=Peak, 1=LowShelf, 2=LowCut, 3=HighShelf, 4=HighCut, 5=Notch) |
| Enabled | Band {N} Enabled |

## Generic Interpretation

For unknown plugins, CubaseTools attempts to match common parameter names:
- **EQ**: Parameters containing "freq", "gain", "band", "q", "width"
- **Compressor**: Parameters containing "threshold", "ratio", "attack", "release", "knee", "makeup"
