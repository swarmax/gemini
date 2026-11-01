"""The body of a loop: the nodes of one pass around it, run by a ``fixed_point`` node.

A plant that closes a loop records one pass around it as a body, in the same graph: ``carry``
nodes stand for the fields of the tear streams, the nodes of the pass follow (they refer freely to
the nodes of the outer graph), and one ``fixed_point`` node, whose operands are the first guess of
every carry and the temperature limits, runs the body on the interpreter until every row has
settled. Its outputs are ``loop_output`` nodes: the converged value of each carry and ``active``,
the rows that did not converge. The nodes of a body belong to it (``Node.body``) and the outer
passes skip them; so does common-subexpression elimination, which merges only inside one body.

``watch`` are the nodes of every outlet of every step of the pass and the values that physics
requires (``ops.require``), ``unframed`` the checks of
the pass that no physics function owns: a row that gets an error into either stops iterating, as
a row does that fails a pass alone. The checks of a body never reach an output of the graph.
"""

from dataclasses import dataclass, field

from gemini.ops import registry

registry.register("carry", "loop", 0)
registry.register("fixed_point", "loop", 0)
registry.register("loop_output", "loop", 1)


@dataclass(eq=False)
class Body:
    """The nodes, checks and results of one pass around a loop."""

    parent: object = None
    carries: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    unframed: list = field(default_factory=list)
    required: list = field(default_factory=list)
    images: tuple = ()
    watch: tuple = ()

    def rollback(self, nodes):
        """Drop what was recorded at or after node index ``nodes``."""
        self.nodes = [node for node in self.nodes if node.index < nodes]
        self.checks = [node for node in self.checks if node.index < nodes]
        self.unframed = [node for node in self.unframed if node.index < nodes]

    def remap(self, survivor, kept):
        """Follow the merged nodes of the graph: ``survivor`` maps a node, ``kept`` lists them."""
        self.nodes = [node for node in self.nodes if node in kept]
        self.checks = [node for node in self.checks if node in kept]
        self.unframed = list(dict.fromkeys(survivor(node) for node in self.unframed))
        self.required = []
        self.images = tuple(survivor(node) for node in self.images)
        self.watch = tuple(dict.fromkeys(survivor(node) for node in self.watch))
