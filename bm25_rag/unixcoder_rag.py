import sys
import os
from typing import List, Tuple
from dotenv import load_dotenv

# Add parent directory to path so we can import unixcoder
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Load environment variables
load_dotenv()

import torch
from unixcoder import UniXcoder

import context_retrieval.retrieval_utils as utils

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UniXcoder("microsoft/unixcoder-base")
model.to(device)

def get_top_k_code_snippets(k: int, query_embedding: torch.Tensor, code_embeddings: List[torch.Tensor], java_file_path: str, line_ranges: List[Tuple[int, int]]) -> List[str]:
    """
    Get the top k code snippets based on cosine similarity to the query embedding.
    
    Args:
        k: Number of snippets to return
        query_embedding: Tensor of shape [768]. The embedding of the bug location code.
        code_embeddings: List of tensors, each of shape [768]. The embeddings of the code snippets.
        java_file_path: Path to the Java file
        line_ranges: List of (start_line, end_line) tuples corresponding to each embedding.
    
    Returns:
        List of top k code snippets (as strings)
    """
    # Stack embeddings to compute all similarities at once
    code_embeddings_tensor = torch.stack(code_embeddings, dim=0)  # [num_snippets, 768]
    query_embedding_expanded = query_embedding.unsqueeze(0)  # [1, 768]
    
    # einsum "ac,bc->ab" with [1,768] and [num_snippets,768] gives [1, num_snippets]: one similarity score per snippet
    similarities = compute_cosine_similarity(query_embedding_expanded, code_embeddings_tensor)
    similarities = similarities.squeeze(0)  # [num_snippets] 
    
    # Get top k indices
    top_k_indices = torch.topk(similarities, k).indices.cpu().tolist()
    
    # Return top k code snippets
    top_k_code_snippets = []
    for i in top_k_indices:
        code = utils.retrieve_code_by_line_number(java_file_path, line_ranges[i])
        top_k_code_snippets.append(code)
    
    return top_k_code_snippets

def embed_code_snippets(method_bodies: List[Tuple[str, Tuple[int, int]]], window_size: int, batch_size: int) -> Tuple[List[torch.Tensor], List[Tuple[int, int]]]:
    """
    Get one embedding for each code snippet, along with line ranges.
    
    Args:
        method_bodies: List of (method_body, (start_line, end_line)) tuples
        window_size: Size of sliding windows
        batch_size: Batch size for embedding
        
    Returns:
        Tuple of:
        - List of embeddings (each tensor of shape [768])
        - List of line ranges (start_line, end_line) tuples - use these to retrieve code
    """
    code_snippets = []
    line_ranges = []  # Track line ranges for each snippet
    for method_body, method_line_range in method_bodies:
        start_line, _ = method_line_range
        # windows is a list of tuples
        windows = get_sliding_windows(method_body, start_line, window_size)
        # Each tuple is in the form of (window_text, (window_start_line, window_end_line))
        for window_text, window_line_range in windows:
            code_snippets.append(window_text)
            line_ranges.append(window_line_range)  # (window_start, window_end)

    batch_embeddings = []
    for i in range(0, len(code_snippets), batch_size):
        batch = code_snippets[i:i+batch_size]
        # Manual padding, otherwise padding will always pad to max_length which may not be necessary
        batch_tokens_no_pad = model.tokenize(batch, max_length=512, mode="<encoder-only>", padding=False)
        max_len_in_batch = max(len(tokens) for tokens in batch_tokens_no_pad)
        batch_tokens = [tokens + [model.config.pad_token_id] * (max_len_in_batch - len(tokens)) 
                        for tokens in batch_tokens_no_pad]
        batch_tensor = torch.tensor(batch_tokens).to(device)
        _, sentence_embeddings = model(batch_tensor)
        # sentence_embeddings is a tensor of shape [batch_size, 768]: one embedding per code snippet
        batch_embeddings.append(sentence_embeddings)
    
    # Flatten all embeddings into a single list (one embedding per snippet)
    all_embeddings = []
    for batch_emb in batch_embeddings:
        for i in range(batch_emb.shape[0]):
            all_embeddings.append(batch_emb[i])  # [768]
    
    return all_embeddings, line_ranges

def embed_bug_location(java_file_path: str, bug_location: Tuple[int, int]) -> torch.Tensor:
    """
    Embed the bug location code. Uses chunking and mean pooling.
    
    Args:
        java_file_path: Path to the Java file
        bug_location: (start_line, end_line) tuple (1-based)
        
    Returns:
        Single embedding tensor of shape [768] (mean pooled across chunks)
    """
    # Get just the buggy lines (not the entire method)
    buggy_code = utils.retrieve_code_by_line_number(java_file_path, bug_location)
    if not buggy_code:
        return None
    
    # Chunk the code (split by lines and group into ~512 token chunks)
    lines = buggy_code.split('\n')
    chunks = []
    current_chunk = []
    current_tokens = 0
    
    for line in lines:
        line_tokens = model.tokenize([line], max_length=512, mode="<encoder-only>", padding=False)[0]
        if current_tokens + len(line_tokens) > 512:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_tokens = len(line_tokens)
        else:
            current_chunk.append(line)
            current_tokens += len(line_tokens)
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    # Embed each chunk
    chunk_embeddings = []
    for chunk in chunks:
        batch_tokens = model.tokenize([chunk], max_length=512, mode="<encoder-only>", padding=True)
        batch_tensor = torch.tensor(batch_tokens).to(device)
        token_embeddings, sentence_embeddings = model(batch_tensor)
        chunk_embeddings.append(sentence_embeddings[0])  # [768]
    
    # Mean pool (if single chunk, mean is just that vector)
    all_chunks = torch.stack(chunk_embeddings, dim=0)  # [num_chunks, 768]
    return torch.mean(all_chunks, dim=0)  # [768]

def compute_cosine_similarity(embedding1: torch.Tensor, embedding2: torch.Tensor) -> torch.Tensor:
    norm_embedding1 = torch.nn.functional.normalize(embedding1, p=2, dim=1)
    norm_embedding2 = torch.nn.functional.normalize(embedding2, p=2, dim=1)
    return torch.einsum("ac,bc->ab", norm_embedding1, norm_embedding2)

def get_sliding_windows(method_body: str, body_start_line: int, window_size: int) -> List[Tuple[str, Tuple[int, int]]]:
    """
    Split method body into sliding windows with line ranges.
    
    Args:
        method_body: The method body code as a string
        body_start_line: The starting line number of the method body in the file (1-based)
        window_size: Number of lines per window
        
    Returns:
        List of tuples: (window_text, (window_start_line, window_end_line))
        Line numbers are 1-based and refer to positions in the original file.
    """
    if not method_body:
        return []
    
    # Get an array of strings, one per line
    lines = method_body.split('\n')

    windows = []
    start = 0
    step = window_size // 2

    while start < len(lines):
        end = min(start + window_size, len(lines))  # Calculate end from start, not increment
        window_str = '\n'.join(lines[start:end])
        
        # Calculate line range in the original file
        # body_start_line is 1-based, start is 0-based within the body
        window_start_line = body_start_line + start
        window_end_line = body_start_line + end - 1  # end is exclusive, so subtract 1
        
        windows.append((window_str, (window_start_line, window_end_line)))

        start += step
        if end == len(lines):
            break
    return windows
