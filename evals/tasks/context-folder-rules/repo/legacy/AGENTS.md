# legacy/

This package is deprecated. Every NEW function added here must call
`warn_legacy("<function name>")` (from `legacy.api`) as its first statement, so we can
see who still uses it. Older functions will be migrated later; do not change them.
