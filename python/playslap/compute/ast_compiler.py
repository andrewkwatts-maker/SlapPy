from __future__ import annotations
import ast
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playslap.struct_registry import StructRegistry

class ASTCompilerError(ValueError):
    pass


class LambdaToWGSL:
    """Compiles a restricted Python lambda AST into a WGSL expression string.

    The lambda takes one argument (conventionally named 'px'). Fields are
    accessed as px.field_name and map to WGSL struct fields.
    """

    BINOP_MAP = {
        ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    }
    CMPOP_MAP = {
        ast.Gt: ">", ast.Lt: "<", ast.GtE: ">=", ast.LtE: "<=", ast.Eq: "==",
    }
    BOOLOP_MAP = {
        ast.And: "&&", ast.Or: "||",
    }

    def __init__(self, registry: "StructRegistry", px_arg: str = "px"):
        self._registry = registry
        self._px_arg = px_arg
        self._used_channels: set[str] = set()

    @property
    def used_channels(self) -> set[str]:
        return set(self._used_channels)

    def compile_lambda(self, fn) -> str:
        """Extract the body of a lambda and compile to WGSL expression."""
        import inspect
        src = inspect.getsource(fn).strip()
        # Find the lambda expression
        src = _extract_lambda_src(src)
        tree = ast.parse(src, mode="eval")
        if not isinstance(tree.body, ast.Lambda):
            raise ASTCompilerError("Expected a lambda expression")
        lam: ast.Lambda = tree.body
        if len(lam.args.args) != 1:
            raise ASTCompilerError("Lambda must take exactly one argument (px)")
        self._px_arg = lam.args.args[0].arg
        return self._expr(lam.body)

    def _expr(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            return self._constant(node)
        if isinstance(node, ast.Attribute):
            return self._attribute(node)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.BoolOp):
            return self._boolop(node)
        if isinstance(node, ast.UnaryOp):
            return self._unaryop(node)
        raise ASTCompilerError(f"Unsupported AST node: {ast.dump(node)}")

    def _constant(self, node: ast.Constant) -> str:
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        if isinstance(node.value, int):
            return str(node.value) + "u" if node.value >= 0 else str(node.value)
        if isinstance(node.value, float):
            return f"{node.value}f"
        raise ASTCompilerError(f"Unsupported constant type: {type(node.value)}")

    def _attribute(self, node: ast.Attribute) -> str:
        if not (isinstance(node.value, ast.Name) and node.value.id == self._px_arg):
            raise ASTCompilerError(
                f"Only '{self._px_arg}.field_name' attribute access is supported"
            )
        field = node.attr
        channels = {name for name, _ in self._registry.channels}
        if field not in channels:
            raise ASTCompilerError(
                f"'{field}' is not a registered channel. Available: {sorted(channels)}"
            )
        self._used_channels.add(field)
        # In the WGSL snippet, channel values are declared as local variables
        return field

    def _binop(self, node: ast.BinOp) -> str:
        op_type = type(node.op)
        if op_type == ast.BitAnd:
            # px.tag & mask — special case for u32 bitwise AND
            left = self._expr(node.left)
            right = self._expr(node.right)
            return f"({left} & {right})"
        if op_type not in self.BINOP_MAP:
            raise ASTCompilerError(f"Unsupported binary operator: {ast.dump(node.op)}")
        op = self.BINOP_MAP[op_type]
        left = self._expr(node.left)
        right = self._expr(node.right)
        return f"({left} {op} {right})"

    def _compare(self, node: ast.Compare) -> str:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ASTCompilerError("Only single comparisons are supported (a op b)")
        op_type = type(node.ops[0])
        if op_type not in self.CMPOP_MAP:
            raise ASTCompilerError(f"Unsupported comparison: {ast.dump(node.ops[0])}")
        op = self.CMPOP_MAP[op_type]
        left = self._expr(node.left)
        right = self._expr(node.comparators[0])
        return f"({left} {op} {right})"

    def _boolop(self, node: ast.BoolOp) -> str:
        op_type = type(node.op)
        if op_type not in self.BOOLOP_MAP:
            raise ASTCompilerError(f"Unsupported boolean op: {type(node.op)}")
        op = self.BOOLOP_MAP[op_type]
        parts = [f"({self._expr(v)})" for v in node.values]
        return f" {op} ".join(parts)

    def _unaryop(self, node: ast.UnaryOp) -> str:
        if isinstance(node.op, ast.Not):
            return f"!({self._expr(node.operand)})"
        if isinstance(node.op, ast.USub):
            return f"(-{self._expr(node.operand)})"
        raise ASTCompilerError(f"Unsupported unary op: {ast.dump(node.op)}")


def compile_apply_shader(
    registry: "StructRegistry",
    filter_lambda,
    mutation_lambda,
    target_channel: str,
    template: str,
) -> str:
    """Compile filter + mutation lambdas into a filled pixel_apply_expr.wgsl snippet.

    Returns the full WGSL source with {{MUTATION_EXPR}} replaced.
    """
    channels = {name: typ for name, typ in registry.channels}
    layout = registry._compute_layout()
    stride_u32s = registry.stride_bytes() // 4

    filter_compiler = LambdaToWGSL(registry)
    mutation_compiler = LambdaToWGSL(registry)

    try:
        filter_wgsl = filter_compiler.compile_lambda(filter_lambda)
        mutation_wgsl = mutation_compiler.compile_lambda(mutation_lambda)
    except Exception as e:
        raise ASTCompilerError(f"Lambda compilation failed: {e}") from e

    all_used = filter_compiler.used_channels | mutation_compiler.used_channels
    if target_channel not in channels:
        raise ASTCompilerError(f"target_channel '{target_channel}' not in registry")

    # Build WGSL snippet: declare channel locals, apply filter, write result
    lines = []
    for ch_name in sorted(all_used):
        ch_type = channels[ch_name]
        ch_off = layout[ch_name] // 4
        if ch_type in ("f32",):
            lines.append(
                f"    let {ch_name} = bitcast<f32>(pixels[base + {ch_off}u]);"
            )
        elif ch_type in ("u32", "i32"):
            lines.append(
                f"    let {ch_name} = pixels[base + {ch_off}u];"
            )
        else:
            # vec types — read as f32 for now (simplified)
            lines.append(
                f"    let {ch_name} = bitcast<f32>(pixels[base + {ch_off}u]);"
            )

    lines.append(f"    if ({filter_wgsl}) {{")
    lines.append(f"        let _result = f32({mutation_wgsl});")
    target_off = layout[target_channel] // 4
    lines.append(
        f"        pixels[base + {target_off}u] = bitcast<u32>(_result);"
    )
    lines.append("    }")

    snippet = "\n".join(lines)
    return template.replace("{{MUTATION_EXPR}}", snippet)


def _extract_lambda_src(source: str) -> str:
    """Extract the lambda expression from a source line that may have surrounding code."""
    import re
    # \blambda\b matches the keyword but not substrings like 'compile_lambda'
    matches = list(re.finditer(r"\blambda\b", source))
    if not matches:
        raise ASTCompilerError("No lambda found in source")
    # Take the last match in case there are multiple — the innermost lambda
    idx = matches[-1].start()
    src = source[idx:]

    # Walk the source tracking paren depth and string state.
    # Stop at the first unbalanced ')' or ',' at depth 0 — those belong to the
    # caller, not the lambda body.
    depth = 0
    in_str = False
    str_char = ""
    end = len(src)
    i = 0
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == "\\" and i + 1 < len(src):
                i += 2          # skip escaped char
                continue
            if ch == str_char:
                in_str = False
        elif ch in ('"', "'"):
            in_str = True
            str_char = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                end = i         # unbalanced ')' — lambda ends here
                break
            depth -= 1
        elif ch in (",", "\n", "\r") and depth == 0:
            end = i             # comma/newline at top level — lambda ends here
            break
        i += 1

    return src[:end].rstrip()
