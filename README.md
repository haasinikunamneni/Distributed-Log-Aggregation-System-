# Distributed Log Aggregation System (CN mini-project)
UDP log clients -> Mininet hosts -> Open vSwitch (OpenFlow 1.3) -> central UDP collector -> SQLite.
An os-ken (Ryu fork) controller classifies critical logs (UDP port 9101) and marks them DSCP 46; Linux tc HTB on the
bottleneck link s1-eth4 gives them priority. See the teammate guide PDF for every step.
Folders: clients/ collector/ sdn/ experiments/ tests/ scripts/ results/ docs/
