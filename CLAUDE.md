Never use worktrees.
No comments in the code.
Do not commit unless asked.
If git has a prepared message, use `git commit --no-edit`.
Else, use Conventional Commits: subject line only, no body, no co-author.
After you edit a C# file, run `dotnet format <project> --include <file> --severity info --exclude-diagnostics IDE0130`, then `csharpier format <file>`.
