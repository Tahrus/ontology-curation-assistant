---
paper_id: "zotero-pdf-222fd192fe"
zotero_key: ""
title: "Ehtesham et al. - 2025 - Supplementary Information"
authors:
year: null
journal: ""
doi: ""
source_pdf: "literature\\Markdown\\Ehtesham et al. - 2025 - Supplementary Information.md"
raw_markdown: "literature\\Markdown\\Ehtesham et al. - 2025 - Supplementary Information.md"
source_collection: ""
extraction_method: "PyMuPDF via BibPipelineCombined"
extraction_date: "2026-06-18T14:38:32.305427+00:00"
cleanup_version: "phase2-cleanup-v1"
extraction_quality: "usable"
metadata_title: "Ehtesham et al. - 2025 - Supplementary Information"
detected_title: ""
title_similarity_score: null
metadata_match_status: "unknown"
document_role: "unknown"
requires_manual_review: false
exclude_from_automatic_llm_extraction: false
include_in_llm_extraction: false
raw_markdown_file: ""
clean_markdown_file: ""
llm_context_file: ""
metadata_report_file: ""
quality_version: ""
id: "zotero-pdf-222fd192fe"
source: "PyMuPDF via BibPipelineCombined"
imported_at: "2026-06-18T14:38:32.305427+00:00"
---

# Ehtesham et al. - 2025 - Supplementary Information

## Abstract

## Notes

## Extracted ontology-relevant information

### Full text

- **Title:** Ehtesham et al. - 2025 - Supplementary Information
- **Source:** Ehtesham et al. - 2025 - Supplementary Information.pdf
- **Pages:** 38
- **Images:** omitted

Supplementary Information for

Dynamics of Batch Protein Precipitation

May 9, 2025

Amirkiarash Ehtesham1, Abhishek Sivaram1, Sara Danielle Siegel2,

John van Zanten2, and Seyed Soheil Mansouri1

1Department of Chemical and Biochemical Engineering,
Technical University of Denmark, Kgs. Lyngby, Denmark

2Golden LEAF Biomanufacturing Training and Education Center (BTEC),
North Carolina State University, Raleigh, NC, USA

Experimental setup:

Phenomenology of population balance model:

2.1
PBM constant parameters or system parameters
. . . . . . . . . . . . . . . . . .

2.2
Solving ODE system: . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .

Differential evolution optimizer internal variables:

PBM optimized results and measurements:

PBM surrogate prediction results:

Neural network internal variables and structure:

Neural network training and validation

Contents

> **Caption:** Figure 1: Experimental setup of the EasyMax 102 instrument in the BTEC laboratory with
Particletrack G400 (on the left side) and the Easyviewer 100 (on the right side).

In precipitation and flocculations and other similar unit operations there are several different

phenomena that can change and alter the particle size distribution. The birth and death terms

of these phenomena are summarized in the following table and they are put together to make

Birth rate
Death rate
```math
Bi=1 = α
```
Nucleation
```math
Bi̸=1 = 0
Di = 0
Bi=1 = 0
Di̸=m ·
```
2·∆Li · Ni
Growth
```math
Bi̸=1 = βi−1 ·
```
2∆Li−1 Ni−1
```math
Di=m = 0
Bi̸=m = γi+1 ·
```
2∆Li+1 Ni+1
Shrinkage
```math
Bi=m = 0
Di = γi ·
```
2·∆Li · Ni

> **Caption:** Table 1: Different mechanisms and phenomena that are present in particulate processes, corresponding discrete birth and death term [1].

Experimental setup:

Phenomenology of population balance model:

equation 1.

∂Ni(υ, t)

∂t
```math
= Bi −Di
```
(1)




m
X

m
X

```math
j=k
```
(1 −0.5 · δj,k)αj,k · βj,k · ηj,k,i · Nj · Nk

Agglomeration
```math
Bi =
```

```math
k=0
```





X

j
γj,i modified · SjNj


```math
Di = Si · Ni
```

Breakage
```math
Bi =
```




```math
Di = Ni · P
```
k αi,k · βi,k · Nk

The second constraint dictates that for instances in which i > j, the fractions must be

nullified, as it is inconceivable for a larger particle to emerge from the breakage of a smaller

Name
System parameter
Value
Units
Used reactor volume
VL
mL
Minimum particle length in the system
Lmin
nm
Maximum particle length in the system
Lmax
cm
Primary particle size
Lp
nm
Fractal Dimension
Df
N/A
Reactor inner diameter
d
Magnetic stirbar diameter
D
Magnetic stirbar height
h1
Density of the system
ρc
kg
m3
Dynamic Viscosity
η
0.8891
mPa·s
Kinematic Viscosity
ν
8.91E-07
m2s−1

To get an initial Distribution of the system, it is assumed that all the protein particles

are primary particles with a size of 2nm. To get the total particles in the system, It can be

To balance computational efficiency with accuracy, the total number of particle bins was set to

30. This binning choice ensures a sufficient resolution to capture particle distribution dynamics

The initial condition was constructed by assuming that all particles present, based on the

specific protein concentration and reaction volume, act as primary particles in the experiment.

The ODE system was then solved using the solve ivp function from Python’s SciPy library,

with the LSODA method chosen due to its robust handling of stiffness, which enhances solution

stability and convergence. The absolute tolerance is 1e-3 and relative tolerance is 1e-6.

> **Caption:** Table 3 lists the internal variables used in the differential evolution (DE) optimizer in Python.

Each variable plays a specific role in how the optimizer searches for the best solution. Below is

• maxiter: This sets the maximum number of iterations (or generations) that the optimizer

will go through. In this case, it is set to 3, meaning the optimizer will refine the population

particle.

2.1
PBM constant parameters or system parameters

> **Caption:** Table 2: System parameters and their respective values and units.

calculated from Equation 2. The density of lysozyme is assumed to be 14300Kg

```math
N0 = protein concentration [g/L] × VL [L] × 6.022 × 1023
```

1000 × 14300
(2)

2.2
Solving ODE system:

effectively.

Differential evolution optimizer internal variables:

a detailed explanation of each variable:

m3 ([2]).

three times before stopping. A low value like this is often used for testing or if quick results

• popsize: This defines the population size, or how many candidate solutions exist in each

generation. Here, it is set to 10, meaning there will be 10 possible solutions being evaluated

at each step. A larger population can give better results but increases computation time.

• strategy: The strategy decides how new candidates are generated. The value ’randtobest1bin’

means the optimizer will use a random vector and the best solution so far to create new

solutions. The ’bin’ part refers to binary crossover, a method for combining solutions.

• mutation: This is a range that controls how much variation (or randomness) is introduced

into the solutions. The values (0.5, 1.5) indicate that the mutation factor can vary within

• recombination: This determines the likelihood of combining information from different

solutions. A value of 0.7 means there is a 70% chance of combining candidate solutions.

This balance helps maintain diversity in the population while converging toward a good

• seed: The seed is used to initialize the random number generator, ensuring reproducibility

```math
of results. In this case, a NumPy random generator (np.random.default rng(seed=7))
```

is used with a fixed seed value of 7. This makes the optimization process deterministic,

By using these settings, the optimizer is configured to quickly test potential solutions while

still maintaining some flexibility and randomness to avoid getting stuck in local minima. These

values might need adjustment depending on the complexity of the problem and the desired

All of the experimental and modeling predictions are given in the following section.

> **Caption:** Table 3: Internal variables used in the differential evolution optimizer in Python

Optimizer
variables
values

maxiter
popsize
strategy
’randtobest1bin’
mutation
(0.5, 1.5)
recombination
0,7
seed
```math
np.random.default rng(seed=7)
```

are needed.

this range, which helps the optimizer explore the solution space more effectively.

solution.

meaning the same results will be obtained every time it is run.

accuracy of the results.

PBM optimized results and measurements:

> **Caption:** Figure 2: Particle size distributions from PBM model predictions and experimental data for
experiment 1

> **Caption:** Figure 3: Median of particle size distributions from PBM prediction and experimental data for
experiment 1

> **Caption:** Figure 4: Particle size distributions from PBM model predictions and experimental data for
experiment 2

> **Caption:** Figure 5: Median of particle size distributions from PBM prediction and experimental data for
experiment 2

> **Caption:** Figure 6: Particle size distributions from PBM model predictions and experimental data for
experiment 3

> **Caption:** Figure 7: Median of particle size distributions from PBM prediction and experimental data for
experiment 3

> **Caption:** Figure 8: Particle size distributions from PBM model predictions and experimental data for
experiment 4

> **Caption:** Figure 9: Median of particle size distributions from PBM prediction and experimental data for
experiment 4

> **Caption:** Figure 10: Particle size distributions from PBM model predictions and experimental data for
experiment 5

> **Caption:** Figure 11: Median of particle size distributions from PBM prediction and experimental data
for experiment 5

> **Caption:** Figure 12: Particle size distributions from PBM model predictions and experimental data for
experiment 6

> **Caption:** Figure 13: Median of particle size distributions from PBM prediction and experimental data
for experiment 6

> **Caption:** Figure 14: Particle size distributions from PBM model predictions and experimental data for
experiment 7

> **Caption:** Figure 15: Median of particle size distributions from PBM prediction and experimental data
for experiment 7

> **Caption:** Figure 16: Particle size distributions from PBM model predictions and experimental data for
experiment 8

> **Caption:** Figure 17: Median of particle size distributions from PBM prediction and experimental data
for experiment 8

> **Caption:** Figure 18: Particle size distributions from PBM model predictions and experimental data for
experiment 9

> **Caption:** Figure 19: Median of particle size distributions from PBM prediction and experimental data
for experiment 9

> **Caption:** Figure 20: Particle size distributions from PBM model predictions and experimental data for
experiment 10

> **Caption:** Figure 21: Median of particle size distributions from PBM prediction and experimental data
for experiment 10

> **Caption:** Figure 22: Particle size distributions from PBM model predictions and experimental data for
experiment 11

> **Caption:** Figure 23: Median of particle size distributions from PBM prediction and experimental data
for experiment 11

> **Caption:** Figure 24: Particle size distributions from PBM model predictions and experimental data for
experiment 12

> **Caption:** Figure 25: Median of particle size distributions from PBM prediction and experimental data
for experiment 12

> **Caption:** Figure 26: Particle size distributions from PBM model predictions and experimental data for
experiment 13

> **Caption:** Figure 27: Median of particle size distributions from PBM prediction and experimental data
for experiment 13

> **Caption:** Figure 28: Particle size distributions from PBM model predictions and experimental data for
experiment 14

> **Caption:** Figure 29: Median of particle size distributions from PBM prediction and experimental data
for experiment 14

> **Caption:** Figure 30: Particle size distributions from PBM model predictions and experimental data for
experiment 15

> **Caption:** Figure 31: Median of particle size distributions from PBM prediction and experimental data
for experiment 15

All of the experimental and surrogate modeling predictions are given in the following section.

These are the same experiments but the PBM model is solved with the surrogate predictions.

> **Caption:** Figure 32: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 1

PBM surrogate prediction results:

> **Caption:** Figure 33: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 1

> **Caption:** Figure 34: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 2

> **Caption:** Figure 35: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 2

> **Caption:** Figure 36: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 3

> **Caption:** Figure 37: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 3

> **Caption:** Figure 38: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 4

> **Caption:** Figure 39: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 4

> **Caption:** Figure 40: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 5

> **Caption:** Figure 41: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 5

> **Caption:** Figure 42: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 6

> **Caption:** Figure 43: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 6

> **Caption:** Figure 44: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 7

> **Caption:** Figure 45: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 7

> **Caption:** Figure 46: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 8

> **Caption:** Figure 47: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 8

> **Caption:** Figure 48: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 9

> **Caption:** Figure 49: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 9

> **Caption:** Figure 50: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 10

> **Caption:** Figure 51: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 10

> **Caption:** Figure 52: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 11

> **Caption:** Figure 53: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 11

> **Caption:** Figure 54: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 12

> **Caption:** Figure 55: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 12

> **Caption:** Figure 56: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 13

> **Caption:** Figure 57: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 13

> **Caption:** Figure 58: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 14

> **Caption:** Figure 59: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 14

> **Caption:** Figure 60: Particle size distributions from ANN-based PBM predictions and experimental data
for experiment 15

> **Caption:** Figure 61: Median of particle size distributions from ANN-based PBM prediction and experimental data for experiment 15

Layer
Type
Input Size
Output Size
Additional Info
First hidden layer
dropout 1
Dropout
```math
Dropout with p = 0.1
```
Second hidden layer
dropout 2
Dropout
```math
Dropout with p = 0.1
```
Output layer
relu
Activation
-
-
ReLU activation after each layer

The table above describes the structure of the Feedforward Artificial Neural Network (FFANN)

used in this study. Each layer of the network serves a specific purpose in processing the data.

• Layer 1 (Linear): This is the first hidden layer of the network. It takes 4 input features

and transforms them into 64 output features. This layer learns initial patterns from the

• Dropout 1: Dropout is a regularization technique used to prevent overfitting by randomly

```math
deactivating some neurons during training. In this case, a dropout rate of p = 0.1 means
```

Neural network internal variables and structure:

> **Caption:** Table 4: Structure of Feedforward Artificial Neural Network (FFANN)

Below is a detailed explanation of the table:

data.

10% of the neurons in this layer are deactivated during each training iteration.

• Layer 2 (Linear): This is the second hidden layer, which takes the 64 outputs from the

previous layer and reduces them to 32 outputs. This layer helps in learning more complex

```math
• Dropout 2: Similar to Dropout 1, this layer applies a dropout rate of p = 0.1 to the 32
```

neurons to further regularize the network and improve its generalization capability.

• Layer 3 (Linear): This is the output layer of the network. It takes 32 inputs and reduces

• ReLU Activation: The ReLU (Rectified Linear Unit) activation function is applied after

each linear layer. ReLU is widely used due to its simplicity and effectiveness in introducing

non-linearity, making it easier for the network to model complex relationships in the data.

The neural network was implemented using the PyTorch library. The design includes two

hidden layers, which are generally sufficient for learning patterns in most datasets. The inclusion

of dropout layers adds regularization, helping to prevent overfitting, while the use of the ReLU

activation function ensures the network is versatile and capable of handling diverse data types.

> **Caption:** Figure 62: Training and validation loss of the ANN over epochs on every fold. The model is
showing signs of overfitting in 3 middle folds.

The model has been trained and the outputs are averaged over 5 folds and 10000 epochs

patterns in the data.

them to 2 outputs, which represent the final predictions of the model.

Neural network training and validation

each. The training and validation loss has been presented in Fig. 62.

In Fig. 62 In two of the folds, the model performs well, with both validation and train-

ing errors following similar trends, indicating consistent learning. However, in other folds, the

validation loss deviates from the training loss, suggesting signs of overfitting. Despite this, aver-

aging the predictions across folds helps regularize the model, reducing the impact of overfitting

on the final results. The number of epochs was set to 10000 to ensure the model had sufficient

[1] N. Nazemzadeh, An integrated multi-scale modeling framework for flocculation processes,

[2] R. E. CANFIELD, Peptides Derived from Tryptic Digestion of Egg White Lysozyme, Journal

of Biological Chemistry 238 (8) (1963) 2691–2697. doi:10.1016/S0021-9258(18)67887-1.

time to learn the data.

## References

Phd dissertation, Technical University of Denmark (2022).
