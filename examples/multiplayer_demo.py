"""
Multiplayer demo -- two players, P2P via DHT, no server needed.

Player 1 (host):   python multiplayer_demo.py host
Player 2 (join):   python multiplayer_demo.py join <ROOM_CODE>

Requires: pip install slappyengine[network]

Architecture notes:
- Peers find each other via Kademlia DHT (BitTorrent bootstrap nodes)
- NAT traversal via STUN (Google public servers) + UDP hole-punching
- LAN fallback via UDP multicast (no internet required on local networks)
- Deterministic lockstep sync: all inputs for tick N collected before simulating
- Works for cone NATs (residential). Symmetric NATs (some corporate) may fail.
"""
import asyncio
import sys

from slappyengine.net import GameSession, SessionConfig, InputFrame
from slappyengine.input import ActionMap


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "host"

    if mode == "host":
        session = await GameSession.host(player_id=0)
        print(f"\n=== Share this room code with other players: {session.room_code} ===\n")
        player_id = 0
    elif mode == "join":
        if len(sys.argv) < 3:
            print("Usage: python multiplayer_demo.py join <ROOM_CODE>")
            return
        room_code = sys.argv[2]
        session = await GameSession.join(room_code, player_id=1)
        player_id = 1
    else:
        print(f"Unknown mode: {mode!r}. Use 'host' or 'join <ROOM_CODE>'.")
        return

    # Set up input action map for this player
    am = ActionMap.wasd(player_id=player_id) if player_id == 0 else ActionMap.arrows(player_id=player_id)

    sync = session.enable_lockstep(num_players=2)

    @session.on_player_joined
    def joined(pid):
        print(f"Player {pid} joined the game!")

    @session.on_player_left
    def left(pid):
        print(f"Player {pid} left the game.")

    print(f"Running as player {player_id}. Simulating 60 ticks at 30 Hz...\n")

    # Simulate a few ticks of lockstep gameplay
    for i in range(60):
        frame = InputFrame(
            tick=sync.tick,
            player_id=player_id,
            actions={"fire": (i % 30 == 0)},
            axes={"move_x": 0.5 if player_id == 0 else -0.5},
        )
        all_frames = await sync.tick_async(frame, session.broadcast)
        for f in all_frames:
            print(f"  Tick {f.tick:3d}  P{f.player_id}: actions={f.actions}  axes={f.axes}")
        await asyncio.sleep(1.0 / 30)

    print("\nDemo complete.")
    await session.close()


if __name__ == "__main__":
    asyncio.run(main())
