# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
# Adapted from microsoft/unixcoder for the AI Agent bug localization

"""
UniXcoder Model Wrapper

UniXcoder is a unified cross-modal pre-trained model for programming language.
It uses a multi-layer transformer model to learn the semantic representations of code.

Reference: https://github.com/microsoft/CodeBERT/tree/master/UniXcoder
"""

import torch
import torch.nn as nn
import random
import numpy as np
from transformers import RobertaTokenizer, RobertaModel, RobertaConfig


class UniXcoder(nn.Module):
    """
    UniXcoder model wrapper for code understanding.
    
    This model is used to encode source code and bug reports into 
    embeddings for semantic similarity comparison.
    """
    
    def __init__(self, model_name: str = "microsoft/unixcoder-base"):
        """
        Initialize UniXcoder model.

        Args:
            model_name: HuggingFace model card name (default: microsoft/unixcoder-base)
        """
        super(UniXcoder, self).__init__()
        self._set_seed(42)
        torch.set_default_dtype(torch.float32)
        
        # Don't use deterministic algorithms if CUDA is not available (causes issues on some systems)
        if torch.cuda.is_available():
            torch.use_deterministic_algorithms(True)
            
        self.tokenizer = RobertaTokenizer.from_pretrained(model_name)
        self.config = RobertaConfig.from_pretrained(model_name)
        self.config.is_decoder = True
        self.model = RobertaModel.from_pretrained(model_name, config=self.config)
        
        self.register_buffer(
            "bias", 
            torch.tril(torch.ones((1024, 1024), dtype=torch.uint8)).view(1, 1024, 1024)
        )
        self.lm_head = nn.Linear(self.config.hidden_size, self.config.vocab_size, bias=False)
        self.lm_head.weight = self.model.embeddings.word_embeddings.weight
        self.lsm = nn.LogSoftmax(dim=-1)
        
        self.tokenizer.add_tokens(["<mask0>"], special_tokens=True)
          
    def _set_seed(self, seed: int):
        """Set random seed for reproducibility."""
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    def tokenize(
        self, 
        inputs: list[str], 
        mode: str = "<encoder-only>", 
        max_length: int = 512, 
        padding: bool = False
    ) -> list[list[int]]:
        """
        Convert strings to token ids.
                
        Args:
            inputs: List of input strings
            max_length: Maximum total source sequence length after tokenization
            padding: Whether to pad source sequence length to max_length
            mode: Which mode the sequence will use (<encoder-only>, <decoder-only>, <encoder-decoder>)
            
        Returns:
            List of token ID lists
        """
        assert mode in ["<encoder-only>", "<decoder-only>", "<encoder-decoder>"]
        assert max_length < 1024
        
        tokens_ids = []
        for x in inputs:
            tokens = self.tokenizer.tokenize(x)
            if mode == "<encoder-only>":
                tokens = tokens[:max_length-4]
                tokens = [self.tokenizer.cls_token, mode, self.tokenizer.sep_token] + tokens + [self.tokenizer.sep_token]
            elif mode == "<decoder-only>":
                tokens = tokens[-(max_length-3):]
                tokens = [self.tokenizer.cls_token, mode, self.tokenizer.sep_token] + tokens
            else:
                tokens = tokens[:max_length-5]
                tokens = [self.tokenizer.cls_token, mode, self.tokenizer.sep_token] + tokens + [self.tokenizer.sep_token]
                
            tokens_id = self.tokenizer.convert_tokens_to_ids(tokens)
            if padding:
                tokens_id = tokens_id + [self.config.pad_token_id] * (max_length - len(tokens_id))
            tokens_ids.append(tokens_id)
        return tokens_ids
            
    def decode(self, source_ids: torch.Tensor) -> list[list[str]]:
        """Convert token ids to strings."""
        predictions = []
        for x in source_ids:
            prediction = []
            for y in x:
                t = y.cpu().numpy()
                t = list(t)
                if 0 in t:
                    t = t[:t.index(0)]
                text = self.tokenizer.decode(t, clean_up_tokenization_spaces=False)
                prediction.append(text)
            predictions.append(prediction)
        return predictions
    
    def forward(self, source_ids: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Obtain token embeddings and sentence embeddings.
        
        Args:
            source_ids: Token IDs tensor
            
        Returns:
            Tuple of (token_embeddings, sentence_embeddings)
        """
        mask = source_ids.ne(self.config.pad_token_id)
        token_embeddings = self.model(
            source_ids, 
            attention_mask=mask.unsqueeze(1) * mask.unsqueeze(2)
        )[0]
        sentence_embeddings = (token_embeddings * mask.unsqueeze(-1)).sum(1) / mask.sum(-1).unsqueeze(-1)
        return token_embeddings, sentence_embeddings

    def generate(
        self, 
        source_ids: torch.Tensor, 
        decoder_only: bool = True, 
        eos_id: int = None, 
        beam_size: int = 5, 
        max_length: int = 64
    ) -> list:
        """Generate sequence given context (source_ids)."""
        # Implementation for code generation if needed
        pass


if __name__ == "__main__":
    # Quick test
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    model = UniXcoder("microsoft/unixcoder-base")
    model.to(device)
    
    test_text = "def hello_world(): print('Hello, World!')"
    tokens = model.tokenize([test_text], mode="<encoder-only>")[0]
    source_ids = torch.tensor([tokens]).to(device)
    
    _, embedding = model(source_ids)
    print(f"Embedding shape: {embedding.shape}")
    print("UniXcoder test successful!")
