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

    def test_clinic_heals_one_to_three_injuries_but_not_four(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(0, 0)] = "clinic"
        player["injuries"] = 2
        app.apply_tile_effect(player)
        self.assertEqual(player["injuries"], 0)
        self.assertIn("healed all", player["last_message"].lower())
        app.apply_tile_effect(player)
        self.assertEqual(player["injuries"], 0)
        self.assertIn("no injuries", player["last_message"].lower())
        player["injuries"] = 4
        app.apply_tile_effect(player)
        self.assertEqual(player["injuries"], 4)
        self.assertIn("go to the er", player["last_message"].lower())

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

    def test_river_is_required_and_start_counts_toward_its_limit(self):
        self.assertFalse(app.river_validation()["ok"])
        app.GAME["board"][(0, 0)] = "river_start"
        self.assertTrue(app.river_validation()["ok"])

    def test_required_tile_validation_rejects_missing_and_duplicate_tiles(self):
        for index, tile in enumerate(sorted(app.REQUIRED_SINGLE_TILES)):
            app.GAME["board"][(index % 10, index // 10)] = tile
        app.GAME["board"][(9, 9)] = "river_start"
        self.assertTrue(app.required_tile_validation()["ok"])

        app.GAME["board"][(9, 9)] = "monster"
        result = app.required_tile_validation()
        self.assertFalse(result["ok"])
        self.assertIn("monster", result["message"])

    def test_lost_player_state_never_contains_the_hidden_coordinates(self):
        player = self.add_player("one", "One", 2, 2)
        player["lost"] = True
        state = app.serialize_player_state_for("one")
        self.assertIsNone(state["you"]["x"])
        self.assertIsNone(state["you"]["y"])

    def test_every_player_message_is_added_to_the_shared_log(self):
        player = self.add_player("one", "One", 2, 2)

        app.set_player_message(player, "A clear test result.")

        self.assertEqual(player["last_message"], "A clear test result.")
        self.assertEqual(app.GAME["logs"][-1], "One: A clear test result.")

        log_count = len(app.GAME["logs"])
        app.set_player_message(player, "A private map note.", shared=False)
        self.assertEqual(player["last_message"], "A private map note.")
        self.assertEqual(len(app.GAME["logs"]), log_count)

    def test_unknown_river_start_does_not_reveal_its_location(self):
        player = self.add_player("one", "One", 2, 2)
        app.GAME["board"][(2, 2)] = "river"
        app.GAME["board"][(8, 8)] = "river_start"

        app.apply_tile_effect(player)

        self.assertTrue(player["lost"])
        self.assertEqual((player["x"], player["y"]), (8, 8))
        self.assertNotIn("8,8", player["known_tiles"])
        state = app.serialize_player_state_for("one")
        self.assertEqual(state["lost_relative_position"], {"x": 0, "y": 0})
        self.assertEqual(state["your_known_tiles"], {"0,0": "river_start"})

    def test_lost_map_uses_relative_coordinates_and_recovers_after_ten_rows_and_columns(self):
        player = self.add_player("one", "One", 5, 5)
        self.add_player("two", "Two", 0, 0)
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)
        player["x"], player["y"] = 6, 5
        player["lost_relative_x"] = 1
        app.remember_lost_tile(player, (6, 5))

        state = app.serialize_player_state_for("one")
        self.assertIn("0,0", state["your_known_tiles"])
        self.assertIn("1,0", state["your_known_tiles"])
        self.assertIsNone(state["you"]["x"])

        player["lost_known_tiles"] = {
            f"{x},{y}": "empty" for x in range(10) for y in range(10)
        }
        self.assertTrue(app.check_lost_map_completion(player))
        self.assertFalse(player["lost"])
        other_state = app.serialize_player_state_for("two")
        self.assertEqual(other_state["public_revealed_players"][0]["sid"], "one")

    def test_new_special_tile_shows_players_who_found_it_in_relative_space(self):
        lost_player = self.add_player("one", "One", 5, 5)
        other = self.add_player("two", "Two", 6, 5)
        other["visited_tiles"] = ["5,5"]
        app.GAME["board"][(5, 5)] = "monster"

        app.enter_lost_state(lost_player, "black_hole")
        app.start_lost_relative_map(lost_player)

        state = app.serialize_player_state_for("one")
        self.assertIn("1,0", state["your_known_players"])
        self.assertEqual(state["your_known_players"]["1,0"][0]["sid"], "two")

        other["lost"] = True
        app.start_lost_relative_map(lost_player)
        state = app.serialize_player_state_for("one")
        self.assertNotIn("1,0", state["your_known_players"])

    def test_river_lost_players_share_their_river_start_relative_map(self):
        one = self.add_player("one", "One", 4, 4)
        two = self.add_player("two", "Two", 4, 4)
        for player in (one, two):
            app.enter_lost_state(player, "river")
            app.start_lost_relative_map(player)

        two["x"], two["y"] = 5, 4
        two["lost_relative_x"] = 1
        app.refresh_lost_river_player_positions()

        state = app.serialize_player_state_for("one")
        self.assertIn("1,0", state["your_known_players"])
        self.assertEqual(state["your_known_players"]["1,0"][0]["sid"], "two")

    def test_shared_river_map_is_kept_for_the_whole_game(self):
        one = self.add_player("one", "One", 4, 4)
        app.enter_lost_state(one, "river")
        app.start_lost_relative_map(one)
        one["x"], one["y"] = 5, 4
        one["lost_relative_x"] = 1
        app.remember_lost_tile(one, (5, 4))
        app.recover_from_lost(one, "Recovered for test.")

        two = self.add_player("two", "Two", 4, 4)
        app.enter_lost_state(two, "river")
        app.start_lost_relative_map(two)
        state = app.serialize_player_state_for("two")
        self.assertIn("1,0", state["your_known_tiles"])

    def test_ten_by_ten_rule_reveals_normal_player_until_they_are_lost(self):
        player = self.add_player("one", "One", 5, 5)
        viewer = self.add_player("two", "Two", 0, 0)
        player["known_tiles"] = {
            f"{x},{y}": "empty" for x in range(10) for y in range(10)
        }

        self.assertTrue(app.check_lost_map_completion(player))
        app.emit_full_state()
        state = app.serialize_player_state_for("two")
        self.assertEqual(state["public_revealed_players"][0]["sid"], "one")
        self.assertIn("9,9", viewer["known_tiles"])

        app.enter_lost_state(player, "black_hole")
        app.emit_full_state()
        state = app.serialize_player_state_for("two")
        self.assertEqual(state["public_revealed_players"], [])

    def test_lost_ten_by_ten_shares_both_sections_when_they_overlap(self):
        player = self.add_player("one", "One", 5, 5)
        viewer = self.add_player("two", "Two", 0, 0)
        app.enter_lost_state(player, "black_hole")
        player["lost_relative_x"] = 0
        player["lost_relative_y"] = 0
        player["known_tiles_before_lost"] = {"0,0": "treasure"}
        player["lost_known_tiles"] = {
            f"{x},{y}": "monster" for x in range(-5, 5) for y in range(-5, 5)
        }

        self.assertTrue(app.check_lost_map_completion(player))
        self.assertEqual(viewer["known_tiles"]["0,0"], "monster")
        self.assertEqual(viewer["known_tiles"]["9,9"], "monster")

    def test_river_map_is_shared_when_a_river_player_completes_ten_by_ten(self):
        player = self.add_player("one", "One", 4, 4)
        viewer = self.add_player("two", "Two", 0, 0)
        app.enter_lost_state(player, "river")
        player["lost_relative_x"] = 0
        player["lost_relative_y"] = 0
        player["lost_known_tiles"] = {
            f"{x},{y}": "river" for x in range(-4, 6) for y in range(-4, 6)
        }

        self.assertTrue(app.check_lost_map_completion(player))
        self.assertEqual(viewer["known_tiles"]["9,9"], "river")

    def test_player_reappears_for_people_who_visited_the_exit_lost_tile(self):
        player = self.add_player("one", "One", 4, 4)
        viewer = self.add_player("two", "Two", 0, 0)
        viewer["visited_tiles"] = ["4,4"]
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)

        app.recover_from_lost(player, "Recovered for test.")
        app.refresh_known_player_positions()

        self.assertIn("4,4", viewer["known_players"])
        self.assertEqual(viewer["known_players"]["4,4"][0]["sid"], "one")

    def test_outer_wall_cannot_be_destroyed(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["game_started"] = True
        app.GAME["player_order"] = ["one"]
        self.assertTrue(app.is_outer_wall(0, 0, "up"))
        self.assertTrue(app.wall_blocks(0, 0, "up"))
        self.assertEqual(player["bombs"], 3)

    def test_outer_wall_bomb_clues_can_complete_a_lost_map(self):
        player = self.add_player("one", "One", 0, 0)
        self.add_player("two", "Two", 9, 9)
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)

        app.remember_lost_outer_wall_bomb(player, "up")
        self.assertTrue(player["lost"])
        self.assertFalse(app.check_lost_map_completion(player))

        app.remember_lost_outer_wall_bomb(player, "left")
        self.assertTrue(app.check_lost_map_completion(player))
        self.assertFalse(player["lost"])
        self.assertEqual(
            app.serialize_player_state_for("two")["public_revealed_players"][0]["sid"],
            "one",
        )

    def test_outer_wall_clue_and_ten_columns_can_complete_a_lost_map(self):
        player = self.add_player("one", "One", 4, 0)
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)
        app.remember_lost_outer_wall_bomb(player, "up")
        player["lost_known_tiles"] = {
            f"{x},0": "empty" for x in range(10)
        }

        self.assertTrue(app.check_lost_map_completion(player))
        self.assertFalse(player["lost"])

    def test_flashlight_counts_as_a_lost_visit_and_recovers_a_familiar_tile(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(1, 0)] = "monster"
        player["known_tiles"] = {"1,0": "monster"}
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)

        revealed = app.reveal_line(player, "right")

        self.assertEqual(revealed, [(1, 0)])
        self.assertIn("1,0", player["visited_tiles"])
        self.assertFalse(player["lost"])
        self.assertIn("flashlight revealed a familiar tile", player["last_message"].lower())

    def test_flashlight_visit_counts_for_lost_special_tile_information(self):
        observer = self.add_player("one", "One", 0, 0)
        lost_player = self.add_player("two", "Two", 1, 0)
        app.GAME["board"][(1, 0)] = "river_start"

        app.reveal_line(observer, "right")
        self.assertIn("1,0", observer["visited_tiles"])

        app.enter_lost_state(lost_player, "river")
        app.start_lost_relative_map(lost_player)
        state = app.serialize_player_state_for("two")
        self.assertEqual(state["your_known_players"]["-1,0"][0]["sid"], "one")

    def test_flashlight_visits_every_revealed_tile_and_logs_special_tiles(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(1, 0)] = "river"
        app.GAME["board"][(2, 0)] = "monster"

        revealed = app.reveal_line(player, "right")

        self.assertIn((1, 0), revealed)
        self.assertIn((2, 0), revealed)
        self.assertTrue({"1,0", "2,0", "9,0"}.issubset(player["visited_tiles"]))
        self.assertEqual(player["known_tiles"]["1,0"], "river")
        self.assertEqual(player["known_tiles"]["2,0"], "monster")
        self.assertTrue(any("flashlight on special tile: river" in line for line in app.GAME["logs"]))
        self.assertTrue(any("flashlight on special tile: monster" in line for line in app.GAME["logs"]))

    def test_special_tile_discovery_adds_the_available_map_information(self):
        explorer = self.add_player("one", "One", 0, 0)
        contributor = self.add_player("two", "Two", 5, 5)
        app.GAME["game_started"] = True
        app.GAME["board"][(1, 0)] = "monster"
        contributor["visited_tiles"] = ["1,0"]
        contributor["known_tiles"] = {"8,8": "exit"}
        contributor["known_open_edges"] = [app.serialize_edge((8, 8), (8, 9))]
        contributor["known_wall_edges"] = [app.serialize_edge((7, 8), (8, 8))]

        app.reveal_line(explorer, "right")

        self.assertEqual(explorer["known_tiles"]["8,8"], "exit")
        self.assertTrue(all(edge in explorer["known_open_edges"] for edge in contributor["known_open_edges"]))
        self.assertTrue(all(edge in explorer["known_wall_edges"] for edge in contributor["known_wall_edges"]))
        self.assertTrue(any("added map information from Two through monster" in line for line in app.GAME["logs"]))

    def test_stepping_on_a_special_tile_adds_its_map_information(self):
        explorer = self.add_player("one", "One", 1, 0)
        contributor = self.add_player("two", "Two", 5, 5)
        app.GAME["game_started"] = True
        app.GAME["board"][(1, 0)] = "river_start"
        contributor["visited_tiles"] = ["1,0"]
        contributor["known_tiles"] = {"7,7": "treasure"}

        app.apply_tile_effect(explorer)

        self.assertEqual(explorer["known_tiles"]["7,7"], "treasure")
        self.assertTrue(any("stepped onto special tile: river_start" in line for line in app.GAME["logs"]))

    def test_lost_tile_discovery_stays_on_the_relative_map(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(1, 0)] = "monster"
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)

        app.reveal_line(player, "right")

        self.assertNotIn("1,0", player["known_tiles"])
        self.assertEqual(player["lost_known_tiles"]["1,0"], "monster")

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

    def test_monster_spawn_grants_resources_but_not_an_extra_turn(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(0, 0)] = "monster"
        player["bullets"] = 0
        player["bombs"] = 0

        app.apply_tile_effect(player, "spawned on", grant_extra_turn=False)

        self.assertEqual(player["bullets"], 1)
        self.assertEqual(player["bombs"], 1)
        self.assertFalse(player["extra_turn"])
        self.assertNotIn("extra turn", player["last_message"].lower())

    def test_river_lost_player_can_continue_through_river_without_new_effects(self):
        player = self.add_player("one", "One", 1, 0)
        app.GAME["board"][(0, 0)] = "river_start"
        app.GAME["board"][(1, 0)] = "river"
        app.enter_lost_state(player, "river")
        app.start_lost_relative_map(player)
        player["river_traveling"] = True
        player["injuries"] = 1

        app.apply_tile_effect(player)

        self.assertTrue(player["lost"])
        self.assertEqual(player["lost_kind"], "river")
        self.assertEqual(player["injuries"], 1)
        self.assertEqual(player["last_message"], "You continue along the river.")

    def test_river_start_injures_without_making_a_player_lost(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(0, 0)] = "river_start"

        app.apply_tile_effect(player)

        self.assertEqual(player["injuries"], 1)
        self.assertFalse(player["lost"])
        self.assertFalse(player["river_traveling"])
        self.assertIn("stayed oriented", player["last_message"].lower())

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

    def test_river_map_fusion_never_recovers_river_lost_players(self):
        one = self.add_player("one", "One", 1, 0)
        two = self.add_player("two", "Two", 1, 0)
        app.GAME["game_started"] = True
        app.GAME["board"][(0, 0)] = "river_start"

        for player in (one, two):
            app.enter_lost_state(player, "river")
            player["x"], player["y"] = 0, 0
            app.start_lost_relative_map(player)

        app.activate_map_fusion(one)
        app.activate_map_fusion(two)

        self.assertTrue(one["lost"])
        self.assertTrue(two["lost"])
        self.assertEqual(one["lost_kind"], "river")
        self.assertEqual(two["lost_kind"], "river")
        self.assertFalse(any("MAP FUSION" in line for line in app.GAME["logs"]))

        app.GAME["turn_number"] += 1
        app.activate_map_fusion(one)

        self.assertTrue(any("MAP FUSION" in line for line in app.GAME["logs"]))
        self.assertTrue(one["lost"])
        self.assertTrue(two["lost"])

    def test_birth_tile_visits_log_every_owner_name(self):
        visitor = self.add_player("visitor", "Visitor", 4, 4)
        visitor["birth_x"], visitor["birth_y"] = 0, 0
        one = self.add_player("one", "One", 4, 4)
        two = self.add_player("two", "Two", 4, 4)

        app.check_birth_spot_discovery(visitor)

        self.assertIn("One", visitor["last_message"])
        self.assertIn("Two", visitor["last_message"])
        self.assertTrue(any(
            "Visitor visited the birth tile of One, Two." in line
            for line in app.GAME["logs"]
        ))

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

    def test_hidden_player_trail_uses_relative_coordinates_until_position_is_known(self):
        viewer = self.add_player("one", "One", 0, 0)
        other = self.add_player("two", "Two", 6, 5)
        other["birth_x"], other["birth_y"] = 5, 5
        other["known_tiles"] = {"5,5": "empty", "6,5": "monster"}
        other["manual_tiles"] = {"7,5": "river"}
        other["known_wall_edges"] = [app.serialize_edge((6, 5), (6, 6))]
        app.GAME["river_lost_map"]["tiles"] = {"0,0": "river_start"}
        app.GAME["river_lost_map"]["wall_edges"] = [app.serialize_edge((0, 0), (1, 0))]
        app.GAME["game_started"] = True

        state = app.serialize_player_state_for("one")
        trail = state["hidden_player_maps"][0]

        self.assertEqual(trail["relative_position"], {"x": 1, "y": 0})
        self.assertEqual(trail["tiles"]["1,0"], "monster")
        self.assertEqual(trail["wall_edges"], [app.serialize_edge((1, 0), (1, 1))])
        self.assertNotIn("manual_tiles", trail)
        self.assertEqual(state["river_map"]["tiles"]["0,0"], "river_start")
        self.assertEqual(state["river_map"]["wall_edges"], [app.serialize_edge((0, 0), (1, 0))])
        self.assertNotIn("x", trail)
        self.assertNotIn("y", trail)

        app.set_relative_player_visibility(viewer, other)
        self.assertEqual(app.serialize_player_state_for("one")["hidden_player_maps"], [])

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
        required_tiles = [
            (2, 2, "treasure"), (3, 2, "fake_treasure"), (0, 9, "exit"),
            (4, 2, "boat"), (5, 2, "raft"), (6, 2, "clinic"),
            (7, 2, "er"), (8, 2, "monster"), (9, 2, "devil"),
            (2, 3, "black_hole"), (3, 3, "flashlight"), (4, 3, "batteries"),
            (5, 3, "armory"), (6, 3, "river_start"),
        ]
        for x, y, tile in required_tiles:
            self.manager.emit("manager_set_tile", {"x": x, "y": y, "tile": tile})
        self.manager.emit("manager_start_game")

    def test_start_rejects_an_incomplete_board(self):
        self.one.emit("player_spawn", {"x": 0, "y": 0})
        self.two.emit("player_spawn", {"x": 1, "y": 0})
        self.manager.emit("manager_start_game")
        messages = self.manager.get_received()
        self.assertFalse(app.GAME["game_started"])
        self.assertTrue(any(
            event["name"] == "error_message" and "river" in event["args"][0]["message"].lower()
            for event in messages
        ))

    def test_manager_cannot_place_a_second_unique_tile(self):
        self.manager.emit("manager_set_tile", {"x": 2, "y": 2, "tile": "monster"})
        self.manager.emit("manager_set_tile", {"x": 3, "y": 2, "tile": "monster"})
        messages = self.manager.get_received()

        self.assertEqual(app.GAME["board"][(2, 2)], "monster")
        self.assertEqual(app.GAME["board"][(3, 2)], "empty")
        self.assertTrue(any(
            event["name"] == "error_message" and "only one monster" in event["args"][0]["message"].lower()
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
        self.assertTrue(one_player["lost"])
        self.assertFalse(any("MAP FUSION" in line for line in app.GAME["logs"]))
        self.assertIsNone(app.GAME["pending_black_hole"])

    def test_lost_outer_wall_bombs_mark_the_map_and_recover_after_two_axes(self):
        self.prepare_startable_game()
        one_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        player = app.GAME["players"][one_sid]
        player["x"], player["y"] = 0, 0
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(one_sid)

        self.one.emit("player_bomb", {"direction": "up"})
        self.assertTrue(player["lost"])
        self.assertEqual(player["bombs"], 2)
        self.assertTrue(player["lost_known_wall_edges"])
        self.assertIn("north outer edge", player["last_message"])

        app.GAME["current_turn_index"] = app.GAME["player_order"].index(one_sid)
        self.one.emit("player_bomb", {"direction": "left"})
        self.assertFalse(player["lost"])
        self.assertEqual(
            app.serialize_player_state_for(app.GAME["player_order"][1])["public_revealed_players"][0]["sid"],
            one_sid,
        )

    def test_flashlight_socket_action_recovers_from_a_familiar_lost_tile(self):
        self.prepare_startable_game()
        one_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        player = app.GAME["players"][one_sid]
        player["x"], player["y"] = 0, 0
        player["items"]["flashlight"] = True
        player["items"]["batteries"] = True
        player["known_tiles"] = {"1,0": "empty"}
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(one_sid)

        self.one.emit("player_flashlight", {"direction": "right"})

        self.assertFalse(player["lost"])
        self.assertIn("1,0", player["visited_tiles"])
        self.assertIn("flashlight revealed a familiar tile", player["last_message"].lower())
        self.assertIn("saw: empty", player["last_message"].lower())
        self.assertIn(f"{player['name']}: {player['last_message']}", app.GAME["logs"])

    def test_dragged_player_can_move_from_river_start_through_the_river(self):
        self.prepare_startable_game()
        player_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        player = app.GAME["players"][player_sid]
        app.GAME["board"][(5, 3)] = "river"
        player["x"], player["y"] = 5, 3
        player["items"]["boat"] = False
        player["items"]["raft"] = False

        app.apply_tile_effect(player)
        self.assertEqual((player["x"], player["y"]), (6, 3))
        self.assertTrue(player["lost"])
        self.assertTrue(player["river_traveling"])
        injuries_after_drag = player["injuries"]
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)

        self.one.emit("player_move", {"direction": "left"})

        self.assertEqual((player["x"], player["y"]), (5, 3))
        self.assertEqual(player["injuries"], injuries_after_drag)
        self.assertTrue(player["river_traveling"])
        self.assertEqual(player["last_message"], "You continue along the river.")

    def test_non_lost_player_can_continue_after_rafting_to_a_known_river_start(self):
        self.prepare_startable_game()
        player_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        player = app.GAME["players"][player_sid]
        app.GAME["board"][(5, 3)] = "river"
        player["x"], player["y"] = 5, 3
        player["known_tiles"]["6,3"] = "river_start"
        player["items"]["raft"] = True

        app.apply_tile_effect(player)
        self.assertEqual((player["x"], player["y"]), (6, 3))
        self.assertFalse(player["lost"])
        self.assertTrue(player["river_traveling"])
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)

        self.one.emit("player_move", {"direction": "left"})

        self.assertEqual((player["x"], player["y"]), (5, 3))
        self.assertFalse(player["lost"])
        self.assertTrue(player["river_traveling"])
        self.assertEqual(player["last_message"], "You continue along the river.")

    def test_player_can_add_and_clear_a_personal_map_note(self):
        self.prepare_startable_game()
        one_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        two_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "Two")
        player = app.GAME["players"][one_sid]
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(two_sid)

        self.one.emit("player_set_map_note", {"x": 2, "y": 2, "tile": "monster"})

        self.assertEqual(player["manual_tiles"]["2,2"], "monster")
        self.assertFalse(any("Map note:" in line for line in app.GAME["logs"]))
        state = app.serialize_player_state_for(one_sid)
        self.assertEqual(state["your_manual_tiles"]["2,2"], "monster")

        app.add_known_tile(player, (2, 2))
        self.assertNotIn("2,2", player["manual_tiles"])

        self.one.emit("player_set_map_note", {"x": 3, "y": 3, "tile": "river"})
        self.one.emit("player_set_map_note", {"x": 3, "y": 3, "tile": ""})
        self.assertNotIn("3,3", player["manual_tiles"])

        self.one.emit("player_toggle_map_wall_note", {"x": 3, "y": 3, "direction": "right"})
        guessed_edge = app.serialize_edge((3, 3), (4, 3))
        self.assertIn(guessed_edge, player["manual_wall_edges"])
        self.assertIn(guessed_edge, app.serialize_player_state_for(one_sid)["your_manual_wall_edges"])

        app.remember_open_edge(player, (3, 3), (4, 3))
        self.assertNotIn(guessed_edge, player["manual_wall_edges"])

    def test_starting_tile_activates_its_effect(self):
        self.manager.emit("manager_set_tile", {"x": 0, "y": 0, "tile": "devil"})
        self.manager.emit("manager_set_tile", {"x": 1, "y": 0, "tile": "treasure"})
        self.manager.emit("manager_set_tile", {"x": 0, "y": 9, "tile": "exit"})
        for x, y, tile in [
            (2, 2, "fake_treasure"), (3, 2, "boat"), (4, 2, "raft"),
            (5, 2, "clinic"), (6, 2, "er"), (7, 2, "monster"),
            (8, 2, "black_hole"), (9, 2, "flashlight"), (2, 3, "batteries"),
            (3, 3, "armory"), (4, 3, "river_start"),
        ]:
            self.manager.emit("manager_set_tile", {"x": x, "y": y, "tile": tile})
        self.one.emit("player_spawn", {"x": 0, "y": 0})
        self.two.emit("player_spawn", {"x": 1, "y": 0})

        self.manager.emit("manager_start_game")

        players = list(app.GAME["players"].values())
        devil_player = next(player for player in players if (player["x"], player["y"]) == (0, 0))
        treasure_player = next(player for player in players if (player["x"], player["y"]) == (1, 0))
        self.assertEqual(devil_player["injuries"], 1)
        self.assertTrue(treasure_player["items"]["treasure"])
        self.assertIn((1, 0), app.GAME["consumed_tiles"])


if __name__ == "__main__":
    unittest.main()
