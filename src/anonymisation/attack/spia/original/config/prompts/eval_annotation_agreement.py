"""
Prompts for annotation agreement evaluation
"""

# ==================== CURRENT VERSION ====================

EVALUATE_ANNOTATION_AGREEMENT_GT = """Below I give you two PII annotation values: the ground truth and a prediction. Decide whether the prediction is correct.

Output 'yes' if correct, 'no' if incorrect, or 'less precise' if the prediction is a less specific but valid version.

Examples of 'yes' (semantic equivalents):
- GT='New York City', Pred='NYC' (abbreviation)
- GT='Republic of Turkey', Pred='Türkiye' (official name change)
- GT='United States', Pred='New York / United States'

Examples of 'less precise' (partial information):
- GT='New York / United States', Pred='New York'
- GT='James Smith', Pred='James' 

Examples of 'no' (different values):
- GT='Boston', Pred='Austin' 
- GT='Paris / France', Pred='Paris / Texas' 

Ground truth: {keyword_a}
Prediction: {keyword_b}

For this pair output 'yes', 'no' or 'less precise':"""


EVALUATE_ANNOTATION_AGREEMENT_AB = """Below I give you two PII annotation values from two different annotators (Annotator A and Annotator B). Decide whether they agree.

Output 'yes' if they agree, 'no' if they disagree, or 'less precise' if one annotation is a less specific but valid version of the other.

Examples of 'yes' (semantic equivalents):
- A='New York City', B='NYC' (abbreviation)
- A='Republic of Turkey', B='Türkiye' (official name change)

Examples of 'less precise' (partial information):
- A='New York / United States', B='New York'
- A='James Smith', B='James'

Examples of 'no' (different values):
- A='Boston', B='Austin'
- A='Paris / France', B='Paris / Texas'

Annotator A: {keyword_a}
Annotator B: {keyword_b}

For this pair output 'yes', 'no' or 'less precise':"""

