import re


class ExpressionEvaluator:
    def __init__(self):
        pass

    def precedence(self, op):
        if op in ("+", "-"):
            return 1
        if op in ("*", "/"):
            return 2
        return 0

    def tokenize(self, expr):
        tokens = []
        i = 0
        prev_type = None
        while i < len(expr):
            if expr[i].isspace():
                i += 1
                continue
            if expr[i] in "+-":
                if (i == 0 or prev_type in ("OP", "LPAREN")) and expr[i] == "-":
                    j = i + 1
                    while j < len(expr) and (expr[j].isdigit() or expr[j] == "."):
                        j += 1
                    tokens.append(("NUMBER", float(expr[i:j])))
                    i = j
                    prev_type = "NUMBER"
                    continue
                elif expr[i] == "+":
                    tokens.append(("OP", "+"))
                    i += 1
                    prev_type = "OP"
                    continue
            if expr[i] in "*/":
                tokens.append(("OP", expr[i]))
                i += 1
                prev_type = "OP"
                continue
            if expr[i] == "(":
                tokens.append(("LPAREN", "("))
                i += 1
                prev_type = "LPAREN"
                continue
            if expr[i] == ")":
                tokens.append(("RPAREN", ")"))
                i += 1
                prev_type = "RPAREN"
                continue
            m = re.match(r"\d+(\.\d*)?|\.\d+", expr[i:])
            if m:
                tokens.append(("NUMBER", float(m.group(0))))
                i += len(m.group(0))
                prev_type = "NUMBER"
                continue
            raise ValueError(f"Token inesperado en expresión: {expr[i:]}")
        return tokens

    def to_postfix(self, tokens):
        output, stack = [], []
        for idx, (type_, value) in enumerate(tokens):
            if type_ == "NUMBER":
                output.append(value)
            elif type_ == "OP":
                if value == "-" and (
                    idx == 0 or tokens[idx - 1][0] in ("OP", "LPAREN")
                ):
                    stack.append("UNARY_MINUS")
                else:
                    while (
                        stack
                        and stack[-1] not in ("(", "UNARY_MINUS")
                        and self.precedence(stack[-1]) >= self.precedence(value)
                    ):
                        output.append(stack.pop())
                    stack.append(value)
            elif type_ == "LPAREN":
                stack.append("(")
            elif type_ == "RPAREN":
                while stack and stack[-1] != "(":
                    output.append(stack.pop())
                stack.pop()
                if stack and stack[-1] == "UNARY_MINUS":
                    output.append(stack.pop())
        while stack:
            output.append(stack.pop())
        return output

    def eval_postfix(self, postfix):
        stack = []
        for token in postfix:
            if isinstance(token, float):
                stack.append(token)
            elif token == "UNARY_MINUS":
                a = stack.pop()
                stack.append(-a)
            else:
                b = stack.pop()
                a = stack.pop()
                if token == "+":
                    stack.append(a + b)
                elif token == "-":
                    stack.append(a - b)
                elif token == "*":
                    stack.append(a * b)
                elif token == "/":
                    if b == 0:
                        raise ZeroDivisionError("División por cero")
                    stack.append(a / b)
        return stack[0]

    def evaluate(self, expr_str, variables=None):
        if variables is None:
            variables = {}
        for i in sorted(variables.keys(), reverse=True):
            expr_str = expr_str.replace(f"${i}", str(variables[i]))
        expr_str = expr_str.replace("x", "*").replace("X", "*")
        if not re.match(r"^[\d\.\s\+\-\*\/\(\)]*$", expr_str):
            raise ValueError(f"Expresión no segura en macro: {expr_str}")
        try:
            tokens = self.tokenize(expr_str)
            postfix = self.to_postfix(tokens)
            return self.eval_postfix(postfix)
        except Exception as e:
            raise ValueError(f"Error evaluando '{expr_str}': {e}")
