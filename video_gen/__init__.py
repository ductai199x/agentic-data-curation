"""Video generation pipeline.

Generates AI video clips paired with our validated real Instagram clips.
Each clip is conditioned on (SALMONN caption, first frame, last frame)
and run through multiple open-source T2V/FLF2V models for architectural
diversity in the detector training set.
"""
