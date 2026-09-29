# Security and data handling

Please report suspected credential exposure, private-data exposure or other security-sensitive issues privately to the repository owner rather than opening a public issue containing sensitive material.

This public repository must not contain confidential customer information, real portfolio data, private asset databases, production credentials, audit/recovery material or secret-bearing configuration.

If sensitive material is committed accidentally:

1. stop further distribution;
2. rotate any exposed credential immediately;
3. remove the material from the current tree;
4. assess whether Git history must be rewritten;
5. invalidate or regenerate affected outputs where necessary.

Production secrets and private operational controls belong in the private core/host environment, not this public shell.
