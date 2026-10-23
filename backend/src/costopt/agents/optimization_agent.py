"""Target-architecture name for the existing optimization analyst."""

from costopt.agents.optimization_analyst import OptimizationAnalystAgent


class OptimizationAgent(OptimizationAnalystAgent):
    """Compatibility-preserving specialization used by the ten-agent graph."""
