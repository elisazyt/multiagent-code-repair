from typing import List, Dict
import re


def build_signatures(signatures_list: List[str]) -> Dict[str, str]:
    """
    Builds a dictionary of documents from a given repository directory and commit.

    Args:
        signatures_list (List[str]): A list of signatures resulting from calling all_signatures_in_class.
        class_name (str, optional): Class name to strip from signatures (e.g., "CategoryPlot").
                                   If provided, strips class prefix to reduce noise in BM25 search.

    Returns:
        dict: A dictionary where keys are original signatures and values are processed signatures.
    """
    signatures = dict()
    for signature in signatures_list:
        stripped = strip_characters(signature)
        split_str = split_words(stripped)
        signatures[signature] = split_str
    return signatures


def build_query(failing_test_list: list[dict[str, str]], buggy_func_signature: str, class_name: str) -> str:
    """
    Build a processed query for BM25 search.
    
    Args:
        failing_test_info (dict[str, str]): The result of running the test suite, which we extract the relevant failing test info from
        buggy_func_signature: Buggy function signature
        class_name: Optional class name to strip from signature
    
    Returns:
        Processed query string (stripped and split)
    """
    failing_test_string = ""
    for failing_test_dict in failing_test_list:
        failing_test_string += failing_test_dict['failing test'] + " " + failing_test_dict['failure message']
    query = failing_test_string + " " + buggy_func_signature
    query = strip_characters(query)
    query = split_words(query)
    return query


def strip_characters(original_str: str) -> str:
    '''
    Replace special characters with spaces: ()[]{}<>,:;/
    This preserves word boundaries for better tokenization.
    '''
    stripped = original_str.replace('(', ' ').replace(')', ' ').replace('[', ' ').replace(']', ' ').replace('{', ' ').replace('}', ' ').replace('<', ' ').replace('>', ' ')
    stripped = stripped.replace(',', ' ').replace(':', ' ').replace(';', ' ').replace('/', ' ')
    # Replace multiple spaces with single space and strip
    import re
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    return stripped


def split_words(stripped_str: str) -> str:
    '''
    Split words into subtokens when the following appear:
        - capital letter (camel case)
        - numbers
        - _ (snake case)
        - :: (test failures)
        - . (package separator)
    '''
    words = []
    for word in stripped_str.split():
        if not word:  # Skip empty strings
            continue
        
        # First split on :: (test failures)
        parts = word.split('::')
        for part in parts:
            # Then split on . (package separator)
            dot_parts = part.split('.')
            for dot_part in dot_parts:
                # Then split on _ (snake case)
                underscore_parts = dot_part.split('_')
                for underscore_part in underscore_parts:
                    if not underscore_part:
                        continue
                    
                    # Split on camel case (before capital letters) and number boundaries
                    # Pattern: split before capital letters (but not at start), and between letters/numbers
                    tokens = re.split(r'(?<![A-Z])(?=[A-Z])|(?<=\d)(?=\D)|(?<=\D)(?=\d)', underscore_part)
                    # Filter out empty strings
                    words.extend([token for token in tokens if token])
    
    return ' '.join(words)