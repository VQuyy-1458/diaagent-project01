"""Start a loopback Neo4j Community instance for the Render demo."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

NEO4J_VERSION = "5.26.32"
JAVA_URL = "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jre/hotspot/normal/eclipse"
NEO4J_URL = f"https://dist.neo4j.org/neo4j-community-{NEO4J_VERSION}-unix.tar.gz"


def install(url, destination):
    destination.mkdir()
    archive = destination.parent / (destination.name + ".tar.gz")
    subprocess.run(["curl", "-fsSL", "--retry", "2", "--max-time", "120",
                    "-o", str(archive), url], check=True)
    subprocess.run(["tar", "-xzf", str(archive), "--strip-components=1",
                    "-C", str(destination)], check=True)
    archive.unlink()


def serve():
    with TemporaryDirectory(prefix="diaagent-") as folder:
        root = Path(folder)
        java, neo4j = root / "java", root / "neo4j"
        uri = "bolt://127.0.0.1:17687"
        env = dict(os.environ, JAVA_HOME=str(java), NEO4J_URI=uri, DIAAGENT_STARTING_DB="1")
        web = subprocess.Popen([sys.executable, "app.py"], env=env)
        db = None
        try:
            install(JAVA_URL, java)
            install(NEO4J_URL, neo4j)
            (neo4j / "conf/neo4j.conf").write_text(
                "server.default_listen_address=127.0.0.1\n"
                "server.bolt.listen_address=127.0.0.1:17687\n"
                "server.http.enabled=false\n"
                "dbms.security.auth_enabled=false\n"
                "dbms.usage_report.enabled=false\n"
                "server.memory.heap.initial_size=80m\n"
                "server.memory.heap.max_size=112m\n"
                "server.memory.pagecache.size=16m\n"
                "server.jvm.additional=-XX:ActiveProcessorCount=1\n"
                "server.jvm.additional=-XX:+UseSerialGC\n"
                "server.jvm.additional=-XX:TieredStopAtLevel=1\n"
                "server.jvm.additional=-XX:ReservedCodeCacheSize=48m\n",
                encoding="utf-8",
            )
            db = subprocess.Popen([str(neo4j / "bin/neo4j"), "console"], env=env,
                                  start_new_session=True)
            while db.poll() is None and web.poll() is None:
                time.sleep(.5)
            return web.poll() or db.poll() or 1
        finally:
            if web is not None and web.poll() is None:
                web.terminate()
                web.wait(timeout=15)
            if db is not None and db.poll() is None:
                os.killpg(db.pid, signal.SIGTERM)
                db.wait(timeout=20)


def install_signal_handler():
    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)


if __name__ == "__main__":
    install_signal_handler()
    sys.exit(serve())

