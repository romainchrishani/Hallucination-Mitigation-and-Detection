# -*- coding: utf-8 -*-
"""Part2-Hallucination detection Part.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1P-zeX_zLgoL8WTViE2EIiMCUhfJZbPFJ
"""

!pip install pypdf
!pip install nltk
!pip install scikit-learn
!pip install numpy
!pip install spacy
!pip install bert_score

import pypdf
import nltk
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import re
import spacy
from difflib import SequenceMatcher
from bert_score import score
import pandas as pd
from nltk.util import ngrams
from collections import Counter
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

nltk.download('punkt')
nltk.download('stopwords')

nlp = spacy.load('en_core_web_sm')
stop_words = set(nltk.corpus.stopwords.words('english'))

def extract_text_from_pdf(pdf_path):
    pages_text = []
    try:
        with open(pdf_path, 'rb') as pdf_file:
            reader = pypdf.PdfReader(pdf_file)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    cleaned_text = clean_text(text)
                    table_sentences = extract_rows_from_table(cleaned_text)
                    pages_text.append((i + 1, table_sentences))
    except Exception as e:
        print(f"Error reading PDF: {e}")
    return pages_text

model_name = "roberta-large-mnli"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)

def clean_text(text):
    text = re.sub(r'-\n', '', text)
    text = re.sub(r'\n(?=\w)', ' ', text)
    text = re.sub(r'\.{2,}', '', text)
    text = re.sub(r'\s{2,}', ' ', text)
    titles = r'(Mr|Mrs|Miss|Ms|Dr)\.'
    text = re.sub(titles, r'\1', text)
    text = re.sub(r'\b([A-Z])\.', r'\1', text)
    #text = re.sub(r'•', '.', text)
    text = re.sub(r'•', '', text)
    text = re.sub(r'(\d)\.', r'\1', text)
    text = re.sub(r'\b(ext)\.(\s|$)', r'\1\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\)\.', ')', text)
    text = re.sub(r'\b[Bb][Ss][Cc]\.', 'BSC', text)
    text = re.sub(r'\b[Mm][Ss][Cc]\.', 'MSC', text)
    text = re.sub(r'uom\.lk', 'uomlk', text)
    text = re.sub(r'\b([Aa])\.[Mm]\.', r'\1m', text)
    text = re.sub(r'\b([Pp])\.[Mm]\.', r'\1m', text)
    text = re.sub(r'mora\.ls', 'morals', text)
    text = re.sub(r'\b[Nn]o\.', 'no', text)
    return text.strip()

def extract_rows_from_table(table_text):
    rows = table_text.split('. ')
    sentences = []
    for row in rows:
        columns = re.split(r'\s{2,}', row)
        if columns:
            sentence = ' '.join(columns).strip()
            if sentence:
                sentences.append(sentence)
    return sentences

def tokenize_sentences(pages_text):
    sentences = []
    sentence_positions = []
    for page_num, page_sentences in pages_text:
        for i, sentence in enumerate(page_sentences):
            tokenized_sentences = nltk.sent_tokenize(sentence)
            for tokenized_sentence in tokenized_sentences:
                sentences.append(tokenized_sentence)
                sentence_positions.append((page_num, i))
    return sentences, sentence_positions

def filter_important_words(sentence):
    doc = nlp(sentence)
    important_words = [
        token.text.lower() for token in doc
        if token.text.lower() not in stop_words and (token.ent_type_ or token.pos_ in {'NOUN', 'VERB', 'PROPN', 'NUM'})
    ]
    return ' '.join(important_words)

def compute_lexical_similarity(reference_sentences, candidate_sentence):
    filtered_candidate = filter_important_words(candidate_sentence)
    filtered_references = [filter_important_words(sentence) for sentence in reference_sentences]
    vectorizer = TfidfVectorizer().fit_transform(filtered_references + [filtered_candidate])
    vectors = vectorizer.toarray()
    cosine_similarities = cosine_similarity(vectors)
    return cosine_similarities[-1][:-1]

def compute_bertscore_similarity(reference_sentences, candidate_sentence, model_type='bert-base-uncased', batch_size=32):
    P, R, F1 = score([candidate_sentence] * len(reference_sentences), reference_sentences, lang='en',
                     model_type=model_type, batch_size=batch_size, verbose=False)
    return F1.numpy()

def check_accuracy(source_text, generated_text):
    inputs = tokenizer.encode_plus(source_text, generated_text, return_tensors='pt', truncation=True)
    outputs = model(**inputs)
    probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
    return probs

LEXICAL_THRESHOLD = 0.3977833266396976
BERTSCORE_THRESHOLD = 0.6154868602752686

def find_most_similar_sentence(reference_sentences, candidate_sentences, sentence_positions):
    all_lexical_scores = []
    all_bertscore_scores = []

    most_similar_sentences = []
    most_similar_positions = []

    for candidate_sentence in candidate_sentences:
        lexical_similarities = compute_lexical_similarity(reference_sentences, candidate_sentence)
        most_similar_index_lexical = np.argmax(lexical_similarities)
        most_similar_sentence_lexical = reference_sentences[most_similar_index_lexical]
        lexical_score = lexical_similarities[most_similar_index_lexical]

        bertscore_similarities = compute_bertscore_similarity(reference_sentences, candidate_sentence)
        most_similar_index_bertscore = np.argmax(bertscore_similarities)
        most_similar_sentence_bertscore = reference_sentences[most_similar_index_bertscore]
        bertscore_score = bertscore_similarities[most_similar_index_bertscore]

        all_lexical_scores.append(lexical_score)
        all_bertscore_scores.append(bertscore_score)

        most_similar_sentences.append((most_similar_sentence_lexical, most_similar_sentence_bertscore))
        most_similar_positions.append((sentence_positions[most_similar_index_lexical], sentence_positions[most_similar_index_bertscore]))

    mean_lexical_score = np.mean(all_lexical_scores)
    mean_bertscore_score = np.mean(all_bertscore_scores)

    return (most_similar_sentences, mean_lexical_score, mean_bertscore_score, most_similar_positions)

def print_matching_sentences(candidate_sentences, most_similar_sentences, positions):
    RED = '\033[91m'
    RESET = '\033[0m'

    def format_accuracy_result(sentence, candidate_sentence):
        accuracy_prob = check_accuracy(sentence, candidate_sentence)
        accuracy_label = torch.argmax(accuracy_prob).item()
        result = "Not Accurate" if accuracy_label == 0 else "Accurate"
        return f"{RED}{result}{RESET}", accuracy_prob, accuracy_label

    lexical_hallucinated = False
    bertscore_hallucinated = False

    for i, candidate_sentence in enumerate(candidate_sentences):
        lexical_sentence, bertscore_sentence = most_similar_sentences[i]
        lexical_position, bertscore_position = positions[i]
        page_num_lexical, sentence_index_lexical = lexical_position
        page_num_bertscore, sentence_index_bertscore = bertscore_position

        accuracy_result_lexical, accuracy_prob_lexical, accuracy_label_lexical = format_accuracy_result(lexical_sentence, candidate_sentence)
        accuracy_result_bertscore, accuracy_prob_bertscore, accuracy_label_bertscore = format_accuracy_result(bertscore_sentence, candidate_sentence)

        if accuracy_label_lexical == 0:
            lexical_hallucinated = True
        if accuracy_label_bertscore == 0:
            bertscore_hallucinated = True

        print(f"Candidate Sentence {i+1}: {candidate_sentence}\n\n"
              f"  Most Similar Sentence (Lexical Similarity): {lexical_sentence}\n"
              f"  Position in PDF (Lexical Similarity): Page {page_num_lexical}, Sentence Index {sentence_index_lexical}\n"
              f"  Accuracy (Lexical Similarity): {accuracy_result_lexical} with probabilities {accuracy_prob_lexical}\n\n"
              f"  Most Similar Sentence (BERTScore): {bertscore_sentence}\n"
              f"  Position in PDF (BERTScore): Page {page_num_bertscore}, Sentence Index {sentence_index_bertscore}\n"
              f"  Accuracy (BERTScore): {accuracy_result_bertscore} with probabilities {accuracy_prob_bertscore}\n")

    return lexical_hallucinated, bertscore_hallucinated

def main(pdf_path, candidate_text):
    pages_text = extract_text_from_pdf(pdf_path)
    reference_sentences, sentence_positions = tokenize_sentences(pages_text)
    clean_candidate_text = clean_text(candidate_text)
    candidate_sentences = nltk.sent_tokenize(clean_candidate_text)

    (most_similar_sentences, mean_lexical_score, mean_bertscore_score, positions) = find_most_similar_sentence(
        reference_sentences, candidate_sentences, sentence_positions)

    lexical_hallucinated, bertscore_hallucinated = print_matching_sentences(candidate_sentences, most_similar_sentences, positions)

    print(f"Mean Lexical Similarity Score: {mean_lexical_score}\n")
    print(f"Mean BERTScore Similarity Score: {mean_bertscore_score}\n")

    if lexical_hallucinated or mean_lexical_score < LEXICAL_THRESHOLD:
        print("The candidate text is lexically hallucinated.")
    else:
        print("The candidate text is not lexically hallucinated.")

    if bertscore_hallucinated or mean_bertscore_score < BERTSCORE_THRESHOLD:
        print("The candidate text is semantically hallucinated.")
    else:
        print("The candidate text is not semantically hallucinated.")

pdf_path = '/content/2023.pdf'

candidate_text = input("Enter the candidate text: ")

if __name__ == "__main__":
    main(pdf_path, candidate_text)