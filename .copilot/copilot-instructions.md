## Tag and Release Policy

- Use lightweight Git tags only.
- Required form:
  git tag vX.Y.Z
  git push origin vX.Y.Z
- Forbidden unless explicitly approved:
  git tag -a ...
  git tag -s ...
  git tag -m ...
  annotated tags
  signed tags
  tag deletion/recreation
  force-pushing tags
  GitHub Release creation/deletion
- Before creating a tag, inspect the previous tag type:
  git cat-file -t <previous-tag>
- If previous project tags are lightweight, the new tag must be lightweight.
- Do not create GitHub Releases unless explicitly requested.
- Do not push anything to upstream.
- upstream is read-only unless explicit human approval is given.
- v1.2.10 is intentionally left as-is even though it is annotated, because it was already pushed and deployed. Future tags must be lightweight.
