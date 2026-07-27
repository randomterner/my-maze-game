import unittest

import app


class MazeGameRuleTests(unittest.TestCase):
    def setUp(self):
        app.GAME = app.new_game_state()

    def add_player(self, sid, name, x, y):
        player = app.create_player(sid, name)
        player.update({"x": x, "y": y, "birth_x": x, "birth_y": y, "spawned": True})
        app.GAME["players"][sid] = player
        return player

    def test_clinic_only_heals_four_injuries(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(0, 0)] = "clinic"
        player["injuries"] = 3
        app.apply_tile_effect(player)
        self.assertEqual(player["injuries"], 3)
        player["injuries"] = 4
        app.apply_tile_effect(player)
        self.assertEqual(player["injuries"], 0)

    def test_river_rejects_unconnected_diagonal_tiles(self):
        app.GAME["board"][(0, 0)] = "river_start"
        app.GAME["board"][(1, 1)] = "river"
        result = app.river_validation()
        self.assertFalse(result["ok"])
        self.assertIn("diagonal", result["message"].lower())

    def test_river_allows_a_connected_diagonal_corner(self):
        app.GAME["board"][(0, 0)] = "river_start"
        app.GAME["board"][(1, 0)] = "river"
        app.GAME["board"][(1, 1)] = "river"

        self.assertTrue(app.river_validation()["ok"])

    def test_river_requires_one_connected_start(self):
        app.GAME["board"][(0, 0)] = "river_start"
        app.GAME["board"][(1, 0)] = "river"
        self.assertTrue(app.river_validation()["ok"])
        app.GAME["board"][(4, 4)] = "river"
        self.assertFalse(app.river_validation()["ok"])

    def test_outer_wall_cannot_be_destroyed(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["game_started"] = True
        app.GAME["player_order"] = ["one"]
        self.assertTrue(app.is_outer_wall(0, 0, "up"))
        self.assertTrue(app.wall_blocks(0, 0, "up"))
        self.assertEqual(player["bombs"], 3)

    def test_last_survivor_wins_and_all_dead_ends_game(self):
        one = self.add_player("one", "One", 0, 0)
        two = self.add_player("two", "Two", 1, 0)
        two["alive"] = False
        app.check_last_player_win()
        self.assertTrue(app.GAME["game_over"])
        self.assertEqual(app.GAME["winner_sid"], "one")

        app.GAME = app.new_game_state()
        one = self.add_player("one", "One", 0, 0)
        two = self.add_player("two", "Two", 1, 0)
        one["alive"] = False
        two["alive"] = False
        app.check_last_player_win()
        self.assertTrue(app.GAME["game_over"])
        self.assertEqual(app.GAME["winner_reason"], "all_players_dead")

    def test_monster_caps_resources_and_grants_an_extra_turn(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(0, 0)] = "monster"
        player["bullets"] = 5
        player["bombs"] = 4

        app.apply_tile_effect(player)

        self.assertEqual(player["bullets"], 5)
        self.assertEqual(player["bombs"], 5)
        self.assertTrue(player["extra_turn"])

    def test_river_boat_and_raft_follow_their_rules(self):
        player = self.add_player("one", "One", 1, 0)
        app.GAME["board"][(0, 0)] = "river_start"
        app.GAME["board"][(1, 0)] = "river"

        player["items"]["boat"] = True
        app.apply_tile_effect(player)
        self.assertEqual((player["x"], player["y"]), (1, 0))
        self.assertEqual(player["injuries"], 0)

        player["items"]["boat"] = False
        player["items"]["raft"] = True
        app.apply_tile_effect(player)
        self.assertEqual((player["x"], player["y"]), (0, 0))
        self.assertEqual(player["injuries"], 0)

    def test_players_keep_separate_maps_when_they_meet(self):
        one = self.add_player("one", "One", 3, 3)
        two = self.add_player("two", "Two", 3, 3)
        one["known_tiles"] = {"0,0": "treasure"}
        two["known_tiles"] = {"9,9": "exit"}

        app.announce_players_on_tile(one)
        app.refresh_known_player_positions()

        self.assertEqual(one["known_tiles"], {"0,0": "treasure"})
        self.assertEqual(two["known_tiles"], {"9,9": "exit"})
        self.assertIn("3,3", one["known_players"])
        self.assertIn("3,3", two["known_players"])

    def test_player_color_is_preserved_and_validated(self):
        player = app.create_player("one", "One", "#A1b2C3")
        self.assertEqual(player["color"], "#a1b2c3")
        self.assertEqual(app.serialize_player_public(player)["color"], "#a1b2c3")
        self.assertEqual(app.create_player("two", "Two", "not-a-color")["color"], "#55e4ff")

class MazeGameSocketTests(unittest.TestCase):
    def setUp(self):
        app.GAME = app.new_game_state()
        app.MANAGER_SID = None
        self.manager = app.socketio.test_client(app.app)
        self.one = app.socketio.test_client(app.app)
        self.two = app.socketio.test_client(app.app)
        self.manager.emit("join_manager")
        self.one.emit("join_player", {"name": "One"})
        self.two.emit("join_player", {"name": "Two"})
        self.manager.get_received()
        self.one.get_received()
        self.two.get_received()

    def tearDown(self):
        self.manager.disconnect()
        self.one.disconnect()
        self.two.disconnect()

    def prepare_startable_game(self):
        self.one.emit("player_spawn", {"x": 0, "y": 0})
        self.two.emit("player_spawn", {"x": 1, "y": 0})
        self.manager.emit("manager_set_tile", {"x": 2, "y": 2, "tile": "treasure"})
        self.manager.emit("manager_set_tile", {"x": 0, "y": 9, "tile": "exit"})
        self.manager.emit("manager_start_game")

    def test_start_requires_one_treasure_and_one_exit(self):
        self.one.emit("player_spawn", {"x": 0, "y": 0})
        self.two.emit("player_spawn", {"x": 1, "y": 0})
        self.manager.emit("manager_start_game")
        messages = self.manager.get_received()
        self.assertFalse(app.GAME["game_started"])
        self.assertTrue(any(
            event["name"] == "error_message" and "treasure" in event["args"][0]["message"].lower()
            for event in messages
        ))

    def test_board_locks_and_new_players_cannot_join_after_start(self):
        self.prepare_startable_game()
        self.assertTrue(app.GAME["game_started"])
        original = app.GAME["board"][(3, 3)]
        self.manager.emit("manager_set_tile", {"x": 3, "y": 3, "tile": "devil"})
        self.assertEqual(app.GAME["board"][(3, 3)], original)

        late_player = app.socketio.test_client(app.app)
        late_player.emit("join_player", {"name": "Late"})
        self.assertEqual(len(app.GAME["players"]), 2)
        messages = late_player.get_received()
        self.assertTrue(any(event["name"] == "error_message" for event in messages))
        late_player.disconnect()

    def test_black_hole_can_place_player_on_an_empty_tile_with_a_player(self):
        self.prepare_startable_game()
        one_sid, two_sid = app.GAME["player_order"][:2]
        one_player = app.GAME["players"][one_sid]
        two_player = app.GAME["players"][two_sid]
        one_player["x"], one_player["y"] = 4, 4
        two_player["x"], two_player["y"] = 5, 5
        app.GAME["pending_black_hole"] = {"player_sid": one_sid}

        self.manager.emit("manager_resolve_black_hole", {"x": 5, "y": 5})
        self.assertEqual((one_player["x"], one_player["y"]), (5, 5))
        self.assertIsNone(app.GAME["pending_black_hole"])

    def test_starting_tile_is_revealed_but_not_activated(self):
        self.manager.emit("manager_set_tile", {"x": 0, "y": 0, "tile": "devil"})
        self.manager.emit("manager_set_tile", {"x": 1, "y": 0, "tile": "treasure"})
        self.manager.emit("manager_set_tile", {"x": 0, "y": 9, "tile": "exit"})
        self.one.emit("player_spawn", {"x": 0, "y": 0})
        self.two.emit("player_spawn", {"x": 1, "y": 0})

        self.manager.emit("manager_start_game")

        players = list(app.GAME["players"].values())
        devil_player = next(player for player in players if (player["x"], player["y"]) == (0, 0))
        treasure_player = next(player for player in players if (player["x"], player["y"]) == (1, 0))
        self.assertEqual(devil_player["injuries"], 0)
        self.assertFalse(treasure_player["items"]["treasure"])
        self.assertNotIn((1, 0), app.GAME["consumed_tiles"])


if __name__ == "__main__":
    unittest.main()
