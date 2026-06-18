# 1682-1687-1213-SCT-4-2025.docx

## LLM-ready full-text Markdown

This Markdown file was generated from a PDF. Images were omitted. Extracted figure captions, table text, equations, references, and article body text are retained where the PDF text layer exposed them. The layout was converted into a single reading order for LLM/RAG ingestion.

## Minimal metadata

- **Title:** 1682-1687-1213-SCT-4-2025.docx
- **Source:** Shahhoseyni et al. - 2025 - Hybrid machine-learning for dynamic plant-wide biomanufacturing.pdf
- **Pages:** 6
- **Author:** Thomas A. Adams II
- **Images:** omitted

<!-- source_page: 1 -->

Research Article - Peer Reviewed Conference Proceeding 
ESCAPE 35 - European Symposium on Computer Aided Process Engineering 
Ghent, Belgium. 6-9 July 2025 
 
Jan F.M. Van Impe, Grégoire Léonard, Satyajeet S. Bhonsale, 
Monika E. Polańska, Filip Logist (Eds.)

Hybrid machine-learning for dynamic plant-wide 
biomanufacturing

Shabnam Shahhoseynia*, Arijit Chakrabortyb, Mohammad Reza Boskabadia, Venkat 
Venkatasubramanianb, Seyed Soheil Mansouria

a Department of Chemical and Biochemical Engineering, Technical University of Denmark, DK-2800 Kgs Lyngby, Denmark

b Department of Chemical Engineering, Columbia University, New York, NY 10027, United States of America  
* Corresponding Author: shabsh@kt.dtu.dk

This study focuses on biomanufacturing case study, i.e. Lovastatin production, employing a hybrid 
modeling framework that combines mechanistic and data-driven approaches. A time-series da-
taset was generated using the KT-Biologics I (KTB1) plantwide model, a dynamic simulation of 
continuous biomanufacturing. The dataset captures critical parameters such as nutrient concen-
trations and API production. The AI-DARWIN framework was used to develop interpretable ma-
chine learning models with constrained functional forms, ensuring both accuracy and clarity. The 
resulting polynomial-based models reveal key relationships between process variables and sys-
tem performance, bridging mechanistic insights with data-driven predictions. The models demon-
strated reasonable accuracy showing minimal difference between the training and testing errors, 
highlighting their strong generalization. This work advances hybrid modeling in biomanufacturing 
by integrating plant-wide mechanistic simulations with interpretable machine learning. The ap-
proach ensures both accuracy and transparency while enabling robust process monitoring and 
control at a ‘plant-wide’ level, contributing to the broader adoption of hybrid modeling in bioman-
ufacturing.

Keywords: Hybrid modeling, Biomanufacturing, Plant-wide modeling, Lovastatin production, Interpretable ma-
chine learning.

https://doi.org/10.69997/sct.174465  
Syst Control Trans 4:1682-1687 (2025) 
1682

ABSTRACT

1. INTRODUCTION

The biomanufacturing of high-value products, such 
as Lovastatin, presents unique challenges due to the 
complex interplay of biological, chemical, and physical 
processes [1]. Lovastatin, a widely used cholesterol-low-
ering drug, is produced through microbial fermentation, 
where variations in nutrient concentrations, reactor con-
ditions, and downstream processing steps significantly 
influence its yield and quality. Developing accurate and 
interpretable models to predict and optimize production 
outcomes is essential for improving efficiency and meet-
ing stringent quality standards.

Traditional modeling approaches in biomanufactur-
ing often rely on mechanistic models, which are 
grounded in physical and biochemical laws. Developing 
these mechanistic models can sometimes be challenging, 
primarily due to the lack of advanced sensing technol-

ogies to gather data (for parameter estimation, model 
validation, etc.) and a limited understanding of multi-
scale phenomenological dynamics. However, data-
driven modeling has shown great promise in capturing 
the behavior of complex systems, if and only, there is suf-
ficient amount of data and right measurement of key 
characteristic phenomena in a process [2]. So, incorpo-
rating domain expertise into the modeling framework is 
crucial.

Bioprocesses, as a prime example of complex sys-
tems, are ideal candidates for data-driven modeling, 
which help bridge gaps in both theoretical knowledge 
and practical modeling [3]. Although this approach can 
handle complex, nonlinear relationships in data, It often 
lacks transparency, making it difficult to trust and inter-
pret its predictions in regulatory and operational con-
texts. To address this limitation, hybrid modeling ap-
proaches that combine mechanistic models with data-

<!-- source_page: 2 -->

Shahhoseyni et al. / LAPSE:2025.0422 
Syst Control Trans 4:1682-1687 (2025) 
1683

driven techniques have gained significant attention. By 
combining numeric AI (machine learning) with symbolic 
AI, a hybrid AI approach can be developed, resulting in 
robust, interpretable models suitable for complex sys-
tems [4].

KT-Biologics I (KTB1) is a dynamic mechanistic sim-
ulation model for continuous biomanufacturing, covering 
the entire Lovastatin production plant [1]. While effective 
in capturing process mechanisms, KTB1 has long running 
times and does not fully clarify how process variables in-
fluence the final output, limiting its use for real-time mon-
itoring and optimization. To address these limitations, a 
hybrid modeling approach integrates mechanistic in-
sights with data-driven modeling. The AI-DARWIN frame-
work [5] enables the discovery of interpretable polyno-
mial models by constraining functional forms, ensuring 
both accuracy and clarity. This approach accelerates 
computation, enhances understanding of variable rela-
tionships, and improves process control efficiency.

This work develops a hybrid model for Lovastatin bi-
omanufacturing, aiming to create an interpretable repre-
sentation of the process that captures its dynamic be-
havior, variable interactions, and plant-wide complexi-
ties. The approach begins by generating time-series da-
tasets from the KTB1 model under varying nutrient con-
ditions to systematically examine the effects of key vari-
ables, such as lactose and adenine, on Lovastatin pro-
duction. These datasets feed into the AI-DARWIN frame-
work, which builds explainable ML models, laying the 
foundation for future optimization of nutrient utilization 
and enabling knowledge transfer to new process scenar-
ios, such as using different microorganisms or producing 
alternative products.

2. SYSTEM DESCRIPTION

2.1. KTB1 Model Description

This model presents a comprehensive framework 
encompassing both the upstream production and down-
stream purification of Lovastatin, a target compound pro-
duced via fermentation. As depicted in Figure 1, the up-
stream process begins with the introduction of key raw 
materials—adenine and lactose—into a mixing unit (M-
101). The mixed medium is then continuously fed into a 
Continuous Stirred-Tank Reactor (CSTR, labeled R-101), 
where the biomass, predominantly Aspergillus terreus, 
facilitates Lovastatin production.

The fermentation broth exiting the CSTR is directed 
to a hydro-cyclone separator (HC-101), which plays a 
pivotal role in separating the mixture into two streams. 
The first stream, rich in biomass, is partially recycled back 
to the CSTR to sustain fermentation. The second stream, 
with lower biomass content (stream 5), is transferred to 
the downstream process.

In the downstream phase, the focus is on a se-
quence of separation and purification steps. Centrifuga-
tion units (C-101 and C-102) initially remove remaining bi-
omass and dense impurities from the solution. Following 
centrifugation, the process advances to nanofiltration 
(NF-101), where Lovastatin is concentrated by retaining 
larger molecules through steric exclusion while smaller 
impurities pass through. Figure 1 illustrates the complete 
process flow for the biomanufacturing of Lovastatin, in-
cluding both the upstream and downstream operations.

Figure 1. Process flow for the biomanufacturing of 
Lovastatin

2.1.1 Dataset

The datasets used in this study were generated to 
systematically explore the relationships between nutrient 
concentrations and Lovastatin API production. Two dis-
tinct datasets were created using the KTB1 mechanistic 
model, each designed to capture specific aspects of the 
nutrient dynamics in the biomanufacturing process. The 
datasets include concentrations of various nutrients 
(such as lactose and adenine), biomass levels in different 
streams, and the Lovastatin API produced production 
plant. In these datasets, only one nutrient concentration 
was varied at a time (by step change) while keeping all 
other process parameters constant. This method of iso-
lating single variables ensures a controlled environment 
to study the individual effects of lactose and adenine on 
Lovastatin production. Each full dataset consists of about 
20000 data points. We used 75% for training and 25% for 
testing, resulting in 15000 training samples and 5000 test 
samples. Dataset 1 contains information on altering lac-
tose concentration (CLA). And Dataset 2 contains infor-
mation on altering adenine concentration (CAD). The 
graphs corresponding to the generated datasets are pre-
sented in Figure 2. A step change in lactose at the start 
of the process, along with a noisy but constant adenine

<!-- source_page: 3 -->

Figure 2. Variables in Dataset 1 (in pink) and Dataset 2 (in greens) were varied, with other variables held constant.

Shahhoseyni et al. / LAPSE:2025.0422 
Syst Control Trans 4:1682-1687 (2025) 
1684

C,AD,1

C,LA,1

4.2

30

4.1

20

g/l

4

g/l

g/l

10

3.9

0

3.8

0
1000
2000

0
1000
2000

C,LA,in

C,AD,in

20.2

5

20.1

4.5

g/l

g/l

g/l

20

4

19.9

19.8

3.5

0
1000
2000

0
1000
2000

Time (hour)

input, were introduced to the model. The noise was in-
tentionally added to simulate real-world scenarios, par-
ticularly in nutrient supply, where fluctuations are often 
observed in one of the inputs. Step changes in lactose 
and adenine, as seen in the first and second datasets, 
can arise from sensor malfunctions, control system er-
rors, or other process deviations, which are common 
faults in industrial processes. These variations result in 
changes to other system variables, such as biomass con-
centration and flow rates. Figure 2 illustrates how these 
variations cause dynamic changes in some of the other 
variables (C,X,4 and Q,R).

2.2. AI-DARWIN Framework

The AI-DARWIN framework is a hybrid AI mechanis-
tic model discovery tool designed to uncover interpreta-
ble and scientifically valid models from data. Unlike tra-
ditional black-box approaches, AI-DARWIN focuses on 
creating explainable models, ensuring that the resulting 
mathematical representations are not only accurate but 
also comprehensible to domain experts. This character-
istic makes it particularly suitable for hybrid modeling 
tasks, such as those encountered in biomanufacturing 
processes. The framework operates by constraining the 
model discovery process to specific functional forms, 
such as polynomials. These constraints allow the gener-
ated models to remain aligned with physical laws and do-
main knowledge, fostering trust and usability in critical 
applications. By imposing such restrictions, AI-DARWIN 
ensures that the final models capture essential relation-
ships without unnecessary complexity, making them eas-
ier to analyze and validate. For the Lovastatin biomanu-
facturing process, AI-DARWIN is applied to time-series 
data generated from the KTB1 mechanistic model. The

C,X,4

Q,R

1.25

30

1.2

l/hr

1.15

25

1.1

1.05

20

0
1000
2000

0
1000
2000

C,X,4

Q,R

1.25

32

1.23

l/hr

30

1.21

1.19

28

0
1000
2000

0
1000
2000

framework systematically evaluates the dataset to un-
cover explicit mathematical relationships between input 
variables, such as nutrient concentrations (e.g., lactose 
and adenine), and output variables, such as Lovastatin 
API production. Moreover, normalization using standard-
ization (subtracting the mean of the training data and di-
viding the difference by the standard deviation of the 
training data) was used to ensure that all input variables 
get weighted appropriately

In the context of model optimization and system 
identification, several frameworks aim to extract mean-
ingful insights from data. One such approach is SINDy [6]. 
While SINDy is not entirely one-shot (first step of param-
eter estimation is followed by iteratively sparsifying the 
coefficients), it comes up with a single best-fit model. AI-
DARWIN comes up with multiple options which allow for 
a broader range of discovery of functional relations be-
tween the input variables. This is particularly useful for 
systems biology models and surrogate models of com-
plex systems. This also can provide a pareto front for fur-
ther examination of the trade-off between simpler but 
less accurate models in contrast to complex but more ac-
curate models. Further, AI-DARWIN provides flexibility to 
incorporate domain-specific constraints, which while lim-
iting in accuracy, reaps rewards in interpretability and 
eventual robustness over unseen data. The resulting 
models are expressed in polynomial form, offering a clear 
interpretation of how each factor influences production 
outcomes. The generated datasets were used to train the 
models, with performance assessed using accuracy met-
rics such as Mean Absolute Error (MAE) and interpreta-
bility metrics like R².

For each dataset, we conducted a series of

<!-- source_page: 4 -->

Target 
Model 
Train MAE 
Test MAE 
C,AD 
9.72 +  0.25 (𝐶𝐶, 𝐿𝐿𝐿𝐿, 1) −0.56 (𝐶𝐶, 𝐿𝐿𝐿𝐿, 12) (𝑄𝑄, 𝑅𝑅) 
0.0198 
0.0198 
C,LA 
75.4 +  6.45 (𝐶𝐶, 𝑋𝑋, 44) −0.60 (𝐶𝐶, 𝑋𝑋, 4)(𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃2) +  5.17 (𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃3) −0.94 (𝑄𝑄, 𝑅𝑅) (𝑅𝑅𝑅𝑅²) 
0.0785 
0.0741 
C,LOV 
12.04 +  5.17 (𝐶𝐶, 𝑋𝑋, 44) −0.52 (𝐶𝐶, 𝑋𝑋, 4)(𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃2) +  6.78(𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃4) −0.45 (𝑄𝑄, 𝑅𝑅)(𝑅𝑅𝐹𝐹2) 
0.0982 
0.0971

Target 
Model 
Train MAE 
Test MAE 
C,AD 
10.18 −1.75 (𝑄𝑄, 𝑅𝑅) × (𝑅𝑅𝐹𝐹2) +  2.06 (𝑄𝑄, 𝑅𝑅4) 
0.0158 
0.0154 
C,LA 
77.04 +  3.18 (𝐶𝐶, 𝑋𝑋, 44) −3.21 (𝑅𝑅𝐹𝐹2)(𝐶𝐶, 𝑋𝑋, 42) +  3.20 (𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃) (𝑄𝑄, 𝑅𝑅2) −2.48 (𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃4) 
0.0970 
0.0959 
C,LOV 
10.43 −0.90 (𝐶𝐶, 𝑋𝑋, 44)  −0.45 (𝑅𝑅𝑅𝑅) +  0.41 (𝐶𝐶, 𝐿𝐿𝐿𝐿, 𝑃𝑃)(𝐶𝐶, 𝑋𝑋, 4) −0.20 (𝐶𝐶, 𝐴𝐴𝐴𝐴, 𝑃𝑃4) 
0.0279 
0.0277

Shahhoseyni et al. / LAPSE:2025.0422 
Syst Control Trans 4:1682-1687 (2025) 
1685

modeling steps to predict the concentrations of lactose 
(C,LA), adenine (C,AD), and lovastatin (C,LOV) in the final 
stream of the plant (stream #10). Figure 3 shows all the 
inputs to the model and outputs. However, in AI-DARWIN, 
we are instructing AI-DARWIN to review all features, se-
lect the ones it deems optimal, and potentially arrive at a 
reduced set of features for the final model.

Figure 3. All the inputs and outputs of the AI-Darwin 
framework (C: Concentration, LA: Lactose, AD: Adenine, 
X: Biomass, LOV: Lovastatin, SP: Setpoint, RF: Recycle 
factor, Q: flow rate; the numbers represent the streams 
number at figure 1).

3. RESULTS AND DISCUSSION

For each dataset several model architectures were 
used, and the performance is compared. Table 1 and 2 
show selected models developed to predict the concen-
tration of two substrates consumed and the API pro-
duced at the outlet of the plant. The results demonstrate 
that the developed modeling framework effectively cap-
tures the complex dynamics of the Lovastatin production  
plant with low training and testing MAE values,

Table 1. Model performance on dataset 1 .

Table 2. Model performance on dataset 2 .

demonstrating high predictive accuracy. Using a combi-
nation of mechanistic principles and data-driven model-
ing, the framework successfully predicts three critical 
outlet concentrations—C,AD, C,LAC, and C,LOV—at the 
plant's downstream stage.

For Dataset 1, the models showed strong perfor-
mance and the minimal error difference between training 
and testing for all the models suggests strong generali-
zation (Table 1 and Figure 4). The polynomial models, ex-
pressed in interpretable forms, highlighted significant 
contributions from key variables such as ‘Q,R’ and ‘C,LA,1’ 
for predicting adenine concentration, and ‘Q,R’, ‘RF’, 
‘C,X,4’, and ‘C,AD,P’ for predicting lactose and lovastatin 
concentrations. These terms reflect critical process in-
teractions and nonlinearities inherent in this biomanufac-
turing system. Adenine concentration in stream 10 
(C,AD), being the simplest model, achieves remarkable 
accuracy (MAEtest=0.0198), indicating that minimal com-
plexity may suffice for certain targets. In contrast, lactose 
and lovastatin concentrations (C,LA and C,LOV) include 
higher-order terms like (C,X,44) and (C,AD,P4), reflecting 
more intricate relationships.

These terms suggest significant nonlinearity in the 
system, consistent with the expected process dynamics. 
The 
inclusion 
of 
interaction 
terms, 
such 
as 
(C,X,4)(C,AD,P2), highlights interdependencies between 
process variables, offering deeper insights into their 
combined effects on product concentrations. While more 
complex models (e.g., C,LA and C,LOV) slightly improve 
accuracy, they may require more computational re-
sources compared to C,AD.

The models developed using Dataset 2 retained this 
interpretability while incorporating additional interactions 
and higher-order terms (Table 2 and Figure 5). For exam-
ple, 
the 
C,LA 
model 
included 
interactions 
like 
(RF2),(C,X,42), and (Q,R2), emphasizing the interdepend-
encies between upstream and downstream variables. 
Similarly, the C,LOV model highlighted the cascading in-
fluence of intermediate concentrations, such as C,LA,P 
on the final product.

The similarity between the MAEs for training and 
testing sets is due to the relatively large dataset and the 
low model complexity, which together reduce the risk of 
overfitting.  The large dataset and high sampling

<!-- source_page: 5 -->

Figure 4 Model performance on the dataset 1

Figure 5. Model performance on the dataset 2

Shahhoseyni et al. / LAPSE:2025.0422 
Syst Control Trans 4:1682-1687 (2025) 
1686

frequency could contribute to the observed similarity be-
tween training and testing MAEs. However, this sampling 
strategy reflects realistic process monitoring where fre-
quent measurements are common. The consistent per-
formance across both subsets suggests that the model 
captures the underlying process behavior without over-
fitting. Nevertheless, we agree that further validation un-
der different operating conditions would provide a 
stronger confirmation of generalizability.

Figure 6 presents the sensitivity analysis performed 
using MAPE. In Dataset 1, the C,AD,P point's distance 
from the center of the radar chart, represented by the 
blue line, indicates the highest sensitivity, meaning minor 
changes in C,AD,P significantly alter the MAPE. Although 
C,AD,P remain highly influential in Dataset 2 (magenta 
line), their impact is slightly reduced, which may be at-
tributed to the overall improved fitting performance of 
the model. Similarly, C,X,4 exhibited significant sensitiv-
ity in both datasets, though to a lesser extent than 
C,AD,P, with Dataset 1 showing a marginally higher sen-
sitivity than Dataset 2. Conversely, RF, Q,R, and C,LA,P 
demonstrated considerably lower sensitivity in both da-
tasets. Despite slight variations in magnitude, the overall 
sensitivity patterns regarding biomass concentration 
were consistent across both datasets, with Dataset 1 
showing a slightly higher sensitivity to changes in C,X,4. 
However, discrepancies in the sensitivities of RF and 
C,AD,P may arise from the fact that these represent two

scenarios modeled for different data conditions (step 
changes in lactose and adenine, respectively).

This modeling framework demonstrates its capabil-
ity to model a plantwide biomanufacturing process, lay-
ing the groundwork for developing digital twins. The in-
terpretability of the polynomial models facilitates under-
standing the underlying system dynamics, while the in-
clusion of complex interactions and nonlinear terms en-
sures the accuracy needed to capture the intricacies of 
the process. For models involving biomass concentration 
at stream 4 (C,X,4 after the fermentation stage) the ki-
netic models in the KTB1 model can be replaced to cal-
culate biomass concentration in the CSTR for new micro-
organisms. By transferring the process dynamics 
knowledge captured in the polynomial models to new 
scenarios for different products, modeling of new sce-
narios can also be performed. This idea will be explored 
in future work, and validation will be required.

Moreover, in the presented study, step changes in 
lactose and adenine concentrations—representing typi-
cal faults encountered in industrial processes—are intro-
duced to the process. Within a broader digital twin frame-
work that includes a fault diagnosis module, once faults 
are detected and diagnosed, the resulting changes in 
Lovastatin concentration at the output can be effectively 
estimated.  This estimation can be done using key

<!-- source_page: 6 -->

Shahhoseyni et al. / LAPSE:2025.0422 
Syst Control Trans 4:1682-1687 (2025) 
1687

process variables, such as flow rates (directly measura-
ble) or biomass concentration (easily calculable), by the 
models proposed in this study. The biomass concentra-
tion can be approximated through a kinetics model within 
the CSTR. This approach provides an opportunity for the 
plant to predict the final product concentration—after 
several units—using operational parameters (recycling 
factor and flow rate) along with the biomass concentra-
tion measured after the fermenter (via the kinetics model) 
beside nutrient concentrations after the hydro-cyclone.

Figure 6. Sensitivity analysis of the models developed 
for lovastatin production using both datasets.

4. CONCLUSION

The polynomial models developed in this study ac-
curately capture the complex dynamics of a plantwide 
bio-manufacturing process, making the framework a val-
uable tool for advancing digital twins. By incorporating 
higher-order and interaction terms, the models effec-
tively represent nonlinear relationships and interactions 
between process variables, enabling predictions under 
varying operational conditions.

The low MAE values for both training and testing da-
tasets indicate that the models generalize well, balancing 
accuracy and robustness. Their explicit functional forms 
provide interpretability, allowing for insight into variable 
sensitivities and interactions, which is essential for de-
veloping digital twins.

Future work will focus on generating more complex 
datasets by varying multiple variables simultaneously, 
providing a richer dataset for model development. Addi-
tionally, testing more advanced models to ensure the se-
lection of the best, yet simplest, representation would 
further validate this framework. This approach, coupled 
with a model selection framework, will optimize the 
trade-off between accuracy, complexity, and interpreta-
bility, expanding the applicability of the models across

diverse scenarios. By using polynomial models to deter-
mine optimal process setpoints, we can adapt the system 
for different scenarios, such as changing the microorgan-
ism to produce a new product, and transfer insights to 
new contexts. Additionally, generating natural language 
explanations from the obtained ML plantwide models by 
incorporating domain-specific knowledge alongside 
large language models (LLMs) is part of the vision for fu-
ture works. This approach could lead to the development 
of a large knowledge model (LKM) [7] tailored for bi-
omanufacturing. This enhances the interoperability of our 
obtained models and can be used to generate additional 
mechanistic insights.

REFERENCES

1. 
Boskabadi, M., Ramin, P., Kager, J., Sin, G., & 
Mansouri, S. S. (2024). KT-Biologics I (KTB1): A 
dynamic simulation model for continuous biologics 
manufacturing. Computers and Chemical 
Engineering, 108770. 
2. 
Venkatasubramanian, V. (2009). Drowning in data: 
Informatics and modeling challenges in a data-rich, 
networked world. AIChE Journal, 55(1), 2-8. 
3. 
Shahhoseyni, S., Greco, L., Sivaram, A., & Mansouri, 
S. S. (2024). A reduced-order hybrid model for 
photobioreactor performance and biomass 
prediction. Algal Research, 84, 103750. 
4. 
Chakraborty, A., Serneels, S., Claussen, H., & 
Venkatasubramanian, V. (2022). Hybrid AI models 
in chemical engineering – A purpose-driven 
perspective. Computer Aided Chemical 
Engineering, 51, 1507-1512. Elsevier. 
5. 
Chakraborty, A., Sivaram, A., & 
Venkatasubramanian, V. (2021). AI-DARWIN: A first 
principles-based model discovery engine using 
machine learning. Computers & Chemical 
Engineering, 154, 107470. 
6. 
Wentz, J., & Doostan, A. (2023). Derivative-based 
SINDy (DSINDy): Addressing the challenge of 
discovering governing equations from noisy data. 
Computer Methods in Applied Mechanics and 
Engineering, 413, 116096. 
7. 
Venkatasubramanian, V., & Chakraborty, A. (2025). 
Quo Vadis ChatGPT? From large language models 
to large knowledge models. Computers & Chemical 
Engineering, 192, 108895.

© 2025 by the authors. Licensed to PSEcommunity.org and PSE 
Press. This is an open access article under the creative com-
mons CC-BY-SA licensing terms. Credit must be given to creator 
and adaptations must be shared under the same terms. See 
https://creativecommons.org/licenses/by-sa/4.0/