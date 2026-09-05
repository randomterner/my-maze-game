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

    def test_public_manager_map_is_revealed_only_after_game_over(self):
        player = self.add_player("one", "One", 3, 4)
        player["known_tiles"] = {"3,4": "empty"}
        player["manual_tiles"] = {"6,6": "private_guess"}
        app.GAME["board"][(9, 9)] = "treasure"
        wall = app.edge_key((8, 9), (9, 9))
        app.GAME["inner_walls"].add(wall)
        app.GAME["game_started"] = True
        for game_over in (False, True, False):
            app.GAME["game_over"] = game_over
            public = app.serialize_public_boards_state()
            full = [b for b in public["boards"] if b.get("manager_map")]
            self.assertEqual(len(full), int(game_over))
            self.assertNotIn("private_guess", str(public))
            if game_over:
                self.assertEqual(full[0]["tiles"], app.serialize_manager_state()["board"])
                self.assertEqual(len(full[0]["tiles"]), 100)
                self.assertEqual(full[0]["tiles"]["9,9"], "treasure")
                self.assertIn(app.serialize_edge(*wall), full[0]["wall_edges"])
                self.assertEqual(len(full[0]["wall_edges"]), 41)
                self.assertEqual(full[0]["players"][0]["x"], 3)
                self.assertEqual(full[0]["birth_spots"]["3,4"], [{"name": "One"}])
            else:
                self.assertFalse(any("treasure" in b["tiles"].values() for b in public["boards"]))

    def test_public_player_stats_do_not_include_private_fields(self):
        player = self.add_player("one", "One", 4, 7)
        player["items"]["boat"] = True
        player["injuries"] = 2
        stats = app.serialize_public_player_stats()[0]
        self.assertEqual(stats["injuries"], 2)
        self.assertTrue(stats["items"]["boat"])
        self.assertFalse({"x", "y", "known_tiles", "manual_tiles", "last_message", "birth_x"} & set(stats))

    def test_empty_and_river_tiles_do_not_trigger_familiar_recovery(self):
        for tile in ("empty", "river", "river_start"):
            with self.subTest(tile=tile):
                app.GAME = app.new_game_state()
                player = self.add_player("one", "One", 1, 1)
                player["x"], player["y"] = 4, 4
                app.GAME["board"][(4, 4)] = tile
                player["known_tiles"] = {"4,4": tile}
                app.enter_lost_state(player, "black_hole")
                app.start_lost_relative_map(player)
                self.assertFalse(app.tile_allows_map_fusion((4, 4)))
                self.assertFalse(app.check_previously_known_recovery(player))
                self.assertFalse(app.check_previously_known_recovery(player, (4, 4), True))
                self.assertTrue(player["lost"])
                player["x"], player["y"] = 1, 1
                app.GAME["board"][(1, 1)] = tile
                self.assertTrue(app.check_birth_spot_discovery(player))
                self.assertFalse(player["lost"])

    def test_same_square_dots_visible_without_recovering_lost_player(self):
        lost = self.add_player("lost", "Lost", 1, 1)
        other = self.add_player("other", "Other", 8, 8)
        lost["x"], lost["y"] = other["x"], other["y"] = 4, 4
        app.enter_lost_state(lost, "black_hole")
        app.start_lost_relative_map(lost)
        app.GAME["turn_number"] += 2
        app.activate_map_fusion(lost)
        app.refresh_known_player_positions()
        lost_view = app.serialize_player_state_for("lost")
        other_view = app.serialize_player_state_for("other")
        self.assertTrue(lost["lost"])
        self.assertEqual(lost_view["your_known_players"]["0,0"][0]["sid"], "other")
        self.assertEqual(other_view["your_known_players"]["4,4"][0]["sid"], "lost")
        self.assertIsNone(lost_view["you"]["x"])

    def test_all_river_lost_players_share_tiles_edges_and_dots(self):
        for index in range(3):
            player = self.add_player(str(index), str(index), 5 + index, 5)
            app.enter_lost_state(player, "river")
            app.start_lost_relative_map(player)
            player["lost_relative_x"] = index
        river = app.GAME["river_lost_map"]
        river["tiles"] = {"0,0": "river_start", "1,0": "river", "2,0": "river"}
        river["wall_edges"] = [app.serialize_edge((2, 0), (2, 1))]
        for sid in ("0", "1", "2"):
            view = app.serialize_player_state_for(sid)
            dots = {p["sid"] for entries in view["your_known_players"].values() for p in entries}
            self.assertEqual(dots, {"0", "1", "2"} - {sid})
            self.assertEqual(view["your_known_tiles"], river["tiles"])
            self.assertEqual(view["your_known_wall_edges"], river["wall_edges"])

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

    def test_knowing_river_start_adds_the_shared_river_map_to_normal_map(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(5, 5)] = "river_start"
        player["known_tiles"] = {"5,5": "river_start"}
        app.GAME["river_lost_map"]["tiles"] = {
            "0,0": "river_start",
            "1,0": "river",
        }
        app.GAME["river_lost_map"]["wall_edges"] = [
            app.serialize_edge((0, 0), (1, 0))
        ]

        state = app.serialize_player_state_for("one")

        self.assertEqual(state["your_known_tiles"]["6,5"], "river")
        self.assertIn("6,5", player["visited_tiles"])
        self.assertIn(
            app.serialize_edge((5, 5), (6, 5)),
            state["your_known_wall_edges"],
        )

    def test_river_lost_players_see_known_river_start_maps_in_river_coordinates(self):
        river_lost = self.add_player("one", "River lost", 5, 5)
        mapper = self.add_player("two", "Mapper", 7, 5)
        app.GAME["board"][(5, 5)] = "river_start"
        app.enter_lost_state(river_lost, "river")
        app.start_lost_relative_map(river_lost)
        mapper["birth_x"], mapper["birth_y"] = 0, 0
        mapper["known_tiles"] = {"5,5": "river_start", "7,5": "monster"}

        state = app.serialize_player_state_for("one")
        trail = next(item for item in state["hidden_player_maps"] if item["sid"] == "two")

        self.assertEqual(trail["relative_position"], {"x": 2, "y": 0})
        self.assertEqual(trail["tiles"]["2,0"], "monster")

    def test_confirmed_shared_map_tiles_count_as_visits_only_when_not_lost(self):
        receiver = self.add_player("one", "Receiver", 0, 0)
        donor = self.add_player("two", "Donor", 1, 1)
        donor["known_tiles"] = {"4,4": "treasure"}

        app.merge_map_knowledge(receiver, donor)
        self.assertIn("4,4", receiver["visited_tiles"])

        lost_receiver = self.add_player("three", "Lost receiver", 0, 0)
        lost_receiver["lost"] = True
        app.merge_map_knowledge(lost_receiver, donor)
        self.assertNotIn("4,4", lost_receiver["visited_tiles"])

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

    def test_known_river_tiles_do_not_end_lost_state_by_themselves(self):
        player = self.add_player("one", "One", 0, 0)
        app.GAME["board"][(1, 0)] = "river"
        player["known_tiles"] = {"1,0": "river"}
        app.enter_lost_state(player, "black_hole")
        player["x"], player["y"] = 1, 0

        self.assertFalse(app.check_previously_known_recovery(player, (1, 0)))
        self.assertTrue(player["lost"])

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
        app.GAME["board"][(1, 0)] = "clinic"
        contributor["visited_tiles"] = ["1,0"]
        contributor["known_tiles"] = {"7,7": "treasure"}

        app.apply_tile_effect(explorer)

        self.assertEqual(explorer["known_tiles"]["7,7"], "treasure")
        self.assertTrue(any("stepped onto special tile: clinic" in line for line in app.GAME["logs"]))

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
        player["in_river"] = True
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
        self.assertFalse(player["in_river"])
        self.assertIn("stayed oriented", player["last_message"].lower())

    def test_own_birth_spot_ends_lost_state(self):
        player = self.add_player("one", "One", 4, 4)
        player["birth_x"], player["birth_y"] = 0, 0
        player["x"], player["y"] = 0, 0
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)

        self.assertTrue(app.check_birth_spot_discovery(player))
        self.assertFalse(player["lost"])

    def test_in_river_tag_is_removed_only_at_the_next_turn_on_dry_land(self):
        player = self.add_player("one", "One", 1, 0)
        app.GAME["board"][(0, 0)] = "river"
        player["in_river"] = True
        player["x"], player["y"] = 1, 0

        self.assertTrue(player["in_river"])
        app.prepare_player_turn(player)
        self.assertFalse(player["in_river"])

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

        self.assertFalse(any("MAP FUSION" in line for line in app.GAME["logs"]))
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

    def test_map_fusion_keeps_maps_and_player_dots_shared_until_a_loss(self):
        one = self.add_player("one", "One", 3, 3)
        two = self.add_player("two", "Two", 3, 3)
        app.GAME["game_started"] = True
        one["known_tiles"] = {"0,0": "treasure"}
        two["known_tiles"] = {"9,9": "exit"}

        app.activate_map_fusion(one)

        self.assertIsNotNone(one["fusion_group"])
        self.assertEqual(one["fusion_group"], two["fusion_group"])
        self.assertEqual(one["known_tiles"], two["known_tiles"])
        self.assertIn("3,3", one["known_players"])
        self.assertEqual(one["known_players"]["3,3"][0]["sid"], "two")

        two["x"], two["y"] = 4, 3
        two["known_tiles"]["4,3"] = "monster"
        app.sync_all_map_fusion_groups()
        app.refresh_known_player_positions()
        self.assertEqual(one["known_tiles"]["4,3"], "monster")
        self.assertEqual(one["known_players"]["4,3"][0]["sid"], "two")

        app.enter_lost_state(one, "black_hole")
        app.refresh_known_player_positions()
        self.assertEqual(one["fusion_group"], two["fusion_group"])
        self.assertNotIn("4,3", two["known_players"])

    def test_recovery_shares_lost_discoveries_with_a_previous_fusion_partner(self):
        one = self.add_player("one", "One", 3, 3)
        two = self.add_player("two", "Two", 3, 3)
        app.GAME["game_started"] = True
        app.activate_map_fusion(one)

        one["x"], one["y"] = 5, 5
        app.enter_lost_state(one, "black_hole")
        app.start_lost_relative_map(one)
        one["x"], one["y"] = 6, 5
        one["lost_relative_x"] = 1
        app.remember_lost_tile(one, (6, 5))

        app.recover_from_lost(one, "Recovered for test.")
        app.sync_all_map_fusion_groups()
        app.refresh_known_player_positions()

        self.assertFalse(one["lost"])
        self.assertEqual(two["known_tiles"]["6,5"], "empty")
        self.assertEqual(one["fusion_group"], two["fusion_group"])
        self.assertEqual(two["known_players"]["6,5"][0]["sid"], "one")

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

    def test_birth_map_link_is_unavailable_when_owner_is_already_lost(self):
        visitor = self.add_player("a", "A", 5, 5)
        owner = self.add_player("b", "B", 5, 5)
        owner["x"], owner["y"] = 8, 8
        owner["known_tiles"] = {"7,7": "treasure"}
        app.enter_lost_state(owner, "black_hole")
        app.start_lost_relative_map(owner)
        app.enter_lost_state(visitor, "black_hole")
        app.start_lost_relative_map(visitor)
        self.assertEqual(visitor["lost_birth_map_sources"], [])
        self.assertNotIn("2,2", visitor["lost_known_tiles"])
        self.assertEqual(visitor["lost_known_players"], {})

    def test_birth_map_can_complete_ten_by_ten_for_either_kind_of_loss(self):
        for kind in ("river", "black_hole"):
            with self.subTest(kind=kind):
                app.GAME = app.new_game_state()
                visitor = self.add_player("a", "A", 4, 5)
                owner = self.add_player("b", "B", 5, 5)
                owner["known_tiles"] = {f"{i},{i}": "empty" for i in range(10)}
                app.enter_lost_state(visitor, kind)
                app.start_lost_relative_map(visitor)
                app.remember_lost_tile(visitor, (5, 5))
                self.assertFalse(visitor["lost"])
                self.assertIn("a", app.GAME["public_revealed_positions"])
                self.assertIn("9,9", visitor["known_tiles"])

    def test_birth_map_familiar_tile_can_recover_but_river_tiles_cannot(self):
        for tile in ("clinic", "river", "river_start"):
            with self.subTest(tile=tile):
                app.GAME = app.new_game_state()
                visitor = self.add_player("a", "A", 4, 5)
                owner = self.add_player("b", "B", 5, 5)
                app.GAME["board"][(7, 7)] = tile
                visitor["known_tiles"] = {"7,7": tile}
                owner["known_tiles"] = {"7,7": tile}
                app.enter_lost_state(visitor, "black_hole")
                app.start_lost_relative_map(visitor)
                app.remember_lost_tile(visitor, (5, 5))
                self.assertEqual(visitor["lost"], tile != "clinic")

    def test_new_loss_clears_birth_map_coordinate_visibility(self):
        visitor = self.add_player("a", "A", 4, 5)
        owner = self.add_player("b", "B", 5, 5)
        owner["x"], owner["y"] = 8, 8
        app.enter_lost_state(visitor, "black_hole")
        app.start_lost_relative_map(visitor)
        app.remember_lost_tile(visitor, (5, 5))
        app.emit_full_state()
        self.assertIn("4,5", owner["known_players"])
        app.enter_lost_state(visitor, "black_hole")
        visitor["x"], visitor["y"] = 1, 1
        app.start_lost_relative_map(visitor)
        app.emit_full_state()
        self.assertEqual(visitor["lost_birth_map_sources"], [])
        self.assertNotIn("1,1", owner["known_players"])

    def test_recovery_restores_own_tiles_and_every_edge_type_in_absolute_coordinates(self):
        for lost_kind in ("river", "black_hole"):
            with self.subTest(lost_kind=lost_kind):
                app.GAME = app.new_game_state()
                player = self.add_player("one", "One", 5, 5)
                stranger = self.add_player("two", "Two", 9, 9)
                app.GAME["board"][(5, 5)] = "clinic"
                player["known_tiles"] = {"0,0": "treasure", "5,5": "clinic"}
                app.enter_lost_state(player, lost_kind)
                player["lost_relative_x"], player["lost_relative_y"] = 2, 1
                player["lost_known_tiles"] = {"0,0": "empty", "1,0": "clinic", "2,1": "clinic"}
                fields = ("known_open_edges", "known_broken_walls", "known_wall_edges")
                for field in fields:
                    player["lost_" + field] = [app.serialize_edge((0, 0), (1, 0))]
                # An outer wall must survive transfer too.
                player["lost_known_wall_edges"].append(app.serialize_edge((-3, 0), (-4, 0)))

                self.assertTrue(app.check_previously_known_recovery(player))
                state = app.serialize_player_state_for("one")
                self.assertFalse(state["you"]["lost"])
                self.assertEqual(state["your_known_tiles"]["4,4"], "clinic")
                self.assertEqual(state["your_known_tiles"]["0,0"], "treasure")
                self.assertIn("4,4", player["visited_tiles"])
                for field in fields:
                    self.assertIn(app.serialize_edge((3, 4), (4, 4)), state["your_" + field])
                self.assertIn(app.serialize_edge((0, 4), (-1, 4)), state["your_known_wall_edges"])
                self.assertNotIn("4,4", stranger["known_tiles"])

    def test_birth_labels_include_all_owners_only_on_discovered_tiles(self):
        viewer = self.add_player("viewer", "Viewer", 0, 0)
        self.add_player("one", "One", 4, 4)
        self.add_player("two", "Two", 4, 4)
        self.add_player("hidden", "Hidden", 8, 8)
        viewer["known_tiles"] = {"4,4": "empty"}
        labels = app.serialize_player_state_for("viewer")["birth_spots"]
        self.assertEqual(labels["0,0"], [{"name": "Viewer"}])
        self.assertEqual(labels["4,4"], [{"name": "One"}, {"name": "Two"}])
        self.assertNotIn("8,8", labels)

        app.enter_lost_state(viewer, "black_hole")
        viewer["x"], viewer["y"] = 3, 4
        app.start_lost_relative_map(viewer)
        app.remember_lost_tile(viewer, (4, 4))
        labels = app.serialize_player_state_for("viewer")["birth_spots"]
        self.assertEqual(labels, {"1,0": [{"name": "One"}, {"name": "Two"}]})

class MazeGameSocketTests(unittest.TestCase):
    def setUp(self):
        app.GAME = app.new_game_state()
        app.MANAGER_SID = None
        app.MANAGER_RECONNECT_TOKEN = None
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
        for client in (self.manager, self.one, self.two):
            if client.is_connected():
                client.disconnect()

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
        # This helper creates a neutral started-game fixture. Tests that need
        # the delayed spawn behavior build their own board below.
        for player in app.GAME["players"].values():
            player["spawn_effect_pending"] = False

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

    def test_public_boards_live_game_over_and_reset_without_joining(self):
        observer = app.socketio.test_client(app.app)
        try:
            self.assertEqual(app.app.test_client().get("/boards").status_code, 200)
            before_players = set(app.GAME["players"])
            observer.emit("watch_public_boards")
            events = observer.get_received()
            self.assertEqual(set(app.GAME["players"]), before_players)
            self.assertFalse(any(e["name"] == "manager_state" for e in events))
            initial = next(e["args"][0] for e in events if e["name"] == "public_boards_state")
            self.assertFalse(any(b.get("manager_map") for b in initial["boards"]))
            app.GAME["game_over"] = True
            app.emit_full_state()
            ended = next(e["args"][0] for e in observer.get_received() if e["name"] == "public_boards_state")
            self.assertEqual(len(ended["boards"][0]["tiles"]), 100)
            self.assertTrue(ended["boards"][0]["manager_map"])
            self.manager.emit("manager_reset_game")
            reset = [e["args"][0] for e in observer.get_received() if e["name"] == "public_boards_state"][-1]
            self.assertFalse(reset["game_over"])
            self.assertFalse(any(b.get("manager_map") for b in reset["boards"]))
        finally:
            observer.disconnect()

    def test_lost_birth_visit_shares_relative_map_and_coordinates_without_recovery(self):
        self.prepare_startable_game()
        one = next(p for p in app.GAME["players"].values() if p["name"] == "One")
        two = next(p for p in app.GAME["players"].values() if p["name"] == "Two")
        one["x"], one["y"] = 4, 5
        two.update(x=7, y=5, birth_x=5, birth_y=5)
        two["known_tiles"] = {"5,5": "empty", "7,5": "empty", "7,6": "clinic"}
        two["known_wall_edges"] = [app.serialize_edge((7, 5), (7, 6))]
        two["manual_tiles"] = {"8,8": "treasure"}
        two["manual_wall_edges"] = [app.serialize_edge((8, 8), (8, 9))]
        app.enter_lost_state(one, "black_hole")
        app.start_lost_relative_map(one)
        app.GAME["turn_number"] += 1
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(one["sid"])

        self.one.emit("player_move", {"direction": "right"})

        state_a = app.serialize_player_state_for(one["sid"])
        state_b = app.serialize_player_state_for(two["sid"])
        self.assertTrue(state_a["you"]["lost"])
        self.assertIsNone(state_a["you"]["x"])
        self.assertEqual(state_a["your_known_tiles"]["3,1"], "clinic")
        self.assertNotIn("7,6", state_a["your_known_tiles"])
        self.assertNotIn("4,3", state_a["your_known_tiles"])
        self.assertIn(app.serialize_edge((3, 0), (3, 1)), state_a["your_known_wall_edges"])
        self.assertNotIn(app.serialize_edge((4, 3), (4, 4)), state_a["your_known_wall_edges"])
        self.assertEqual(state_a["your_known_players"]["3,0"][0]["sid"], two["sid"])
        self.assertEqual(state_b["your_known_players"]["5,5"][0]["sid"], one["sid"])
        trail = next(t for t in state_a["hidden_player_maps"] if t["sid"] == two["sid"])
        self.assertEqual(trail["relative_position"], {"x": 3, "y": 0})
        self.assertEqual(trail["tiles"]["3,1"], "clinic")

        two["x"] = 8
        app.add_known_tile(two, (8, 5))
        app.emit_full_state()
        self.assertEqual(one["lost_known_players"]["4,0"][0]["sid"], two["sid"])
        self.assertTrue(one["lost"])
        app.enter_lost_state(two, "black_hole")
        app.start_lost_relative_map(two)
        app.emit_full_state()
        self.assertFalse(any(p["sid"] == two["sid"] for entries in one["lost_known_players"].values() for p in entries))
        self.assertTrue(one["lost"])

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

    def test_player_cannot_reconnect_without_manager_approval(self):
        old_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "One")
        original_player = app.GAME["players"][old_sid]
        original_player["items"]["boat"] = True
        original_player["spawned"] = True

        self.one.disconnect()

        self.assertIn(old_sid, app.GAME["players"])
        self.assertFalse(app.GAME["players"][old_sid]["connected"])
        self.assertIn("temporarily disconnected", app.GAME["logs"][-1])

        reconnected_client = app.socketio.test_client(app.app)
        try:
            reconnected_client.emit("resume_player", {})
            self.assertIn(old_sid, app.GAME["players"])
            self.assertFalse(app.GAME["players"][old_sid]["connected"])
            self.assertTrue(any(
                event["name"] == "resume_failed"
                and "manager approval" in event["args"][0]["message"].lower()
                for event in reconnected_client.get_received()
            ))
        finally:
            reconnected_client.disconnect()

    def test_connected_name_does_not_create_a_manager_reconnect_popup(self):
        another_tab = app.socketio.test_client(app.app)
        try:
            another_tab.emit("join_player", {"name": "One"})
            self.assertEqual(app.GAME["pending_reconnect_claims"], {})
            self.assertTrue(any(
                event["name"] == "error_message"
                and "already in use" in event["args"][0]["message"].lower()
                for event in another_tab.get_received()
            ))
            self.assertFalse(any(
                event["name"] == "reconnect_claim_requested"
                for event in self.manager.get_received()
            ))
        finally:
            another_tab.disconnect()

    def test_manager_can_approve_a_new_tab_for_a_disconnected_players_name(self):
        old_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "One")
        original_player = app.GAME["players"][old_sid]
        original_player["items"]["raft"] = True
        original_player["spawned"] = True
        self.one.disconnect()

        replacement_tab = app.socketio.test_client(app.app)
        try:
            replacement_tab.emit("join_player", {"name": "One", "color": "#123456"})
            self.assertIn(old_sid, app.GAME["players"])
            self.assertFalse(app.GAME["players"][old_sid]["connected"])
            claim_sid = next(iter(app.GAME["pending_reconnect_claims"]))
            self.assertTrue(any(
                event["name"] == "reconnect_claim_requested"
                and event["args"][0]["sid"] == claim_sid
                for event in self.manager.get_received()
            ))

            self.manager.emit("manager_approve_reconnect", {"sid": claim_sid})

            new_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "One")
            restored_player = app.GAME["players"][new_sid]
            self.assertNotEqual(new_sid, old_sid)
            self.assertTrue(restored_player["connected"])
            self.assertTrue(restored_player["items"]["raft"])
            self.assertTrue(restored_player["spawned"])
            self.assertEqual(restored_player["color"], "#123456")
            self.assertEqual(app.GAME["pending_reconnect_claims"], {})
            self.assertTrue(any(
                event["name"] == "resumed_as_player"
                for event in replacement_tab.get_received()
            ))
        finally:
            replacement_tab.disconnect()

    def test_disconnected_players_keep_their_turn_until_manager_confirms_left(self):
        self.prepare_startable_game()
        one_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "One")
        two_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "Two")
        app.GAME["player_order"] = [one_sid, two_sid]
        app.GAME["current_turn_index"] = 0

        self.one.disconnect()

        self.assertEqual(app.current_turn_sid(), one_sid)
        self.manager.emit("manager_confirm_player_left", {"sid": one_sid})

        self.assertNotIn(one_sid, app.GAME["players"])
        self.assertEqual(app.current_turn_sid(), two_sid)

    def test_moving_onto_another_player_starts_map_fusion_and_shows_both_dots(self):
        self.prepare_startable_game()
        one_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "One")
        two_sid = next(sid for sid, player in app.GAME["players"].items() if player["name"] == "Two")
        one = app.GAME["players"][one_sid]
        two = app.GAME["players"][two_sid]
        one["known_tiles"] = {"0,0": "empty"}
        two["known_tiles"] = {"1,0": "empty", "9,9": "exit"}
        app.GAME["player_order"] = [one_sid, two_sid]
        app.GAME["current_turn_index"] = 0

        self.one.emit("player_move", {"direction": "right"})

        self.assertEqual((one["x"], one["y"]), (1, 0))
        self.assertEqual(one["fusion_group"], two["fusion_group"])
        self.assertIsNotNone(one["fusion_group"])
        self.assertEqual(one["known_tiles"], two["known_tiles"])
        self.assertEqual(one["known_players"]["1,0"][0]["sid"], two_sid)
        self.assertEqual(two["known_players"]["1,0"][0]["sid"], one_sid)

    def test_manager_can_resume_after_a_temporary_disconnect(self):
        reconnect_token = app.MANAGER_RECONNECT_TOKEN
        self.manager.disconnect()
        self.assertIsNone(app.MANAGER_SID)

        reconnected_manager = app.socketio.test_client(app.app)
        try:
            reconnected_manager.emit("resume_manager", {"reconnect_token": reconnect_token})
            received = reconnected_manager.get_received()
            resumed = next(event for event in received if event["name"] == "resumed_as_manager")
            self.assertEqual(app.MANAGER_SID, resumed["args"][0]["sid"])
        finally:
            reconnected_manager.disconnect()

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
        app.GAME["board"][(1, 0)] = "clinic"
        player["known_tiles"] = {"1,0": "clinic"}
        app.enter_lost_state(player, "black_hole")
        app.start_lost_relative_map(player)
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(one_sid)

        self.one.emit("player_flashlight", {"direction": "right"})

        self.assertFalse(player["lost"])
        self.assertIn("1,0", player["visited_tiles"])
        self.assertIn("flashlight revealed a familiar tile", player["last_message"].lower())
        self.assertIn("saw: clinic", player["last_message"].lower())
        self.assertIn(f"{player['name']}: {player['last_message']}", app.GAME["logs"])
        recovered_state = app.serialize_player_state_for(one_sid)
        self.assertIn("0,0", recovered_state["your_known_tiles"])
        self.assertIn(app.serialize_edge((0, 0), (1, 0)), recovered_state["your_known_open_edges"])

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
        self.assertTrue(player["in_river"])
        injuries_after_drag = player["injuries"]
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)

        self.one.emit("player_move", {"direction": "left"})

        self.assertEqual((player["x"], player["y"]), (5, 3))
        self.assertEqual(player["injuries"], injuries_after_drag)
        self.assertTrue(player["in_river"])
        self.assertEqual(player["last_message"], "You continue along the river.")

    def test_own_river_birth_tile_ends_lost_state_when_the_player_returns_to_it(self):
        self.prepare_startable_game()
        player_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        player = app.GAME["players"][player_sid]
        app.GAME["board"][(5, 3)] = "river"
        player["birth_x"], player["birth_y"] = 5, 3
        player["x"], player["y"] = 5, 3
        player["items"]["boat"] = False
        player["items"]["raft"] = False

        app.apply_tile_effect(player)
        self.assertTrue(player["lost"])
        self.assertEqual((player["x"], player["y"]), (6, 3))
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)

        self.one.emit("player_move", {"direction": "left"})

        self.assertFalse(player["lost"])
        self.assertTrue(player["in_river"])
        self.assertEqual((player["x"], player["y"]), (5, 3))
        recovered_state = app.serialize_player_state_for(player_sid)
        self.assertEqual(recovered_state["your_known_tiles"]["6,3"], "river_start")
        self.assertIn(app.serialize_edge((5, 3), (6, 3)), recovered_state["your_known_open_edges"])

    def test_river_continuation_still_works_after_birth_spot_recovery(self):
        self.prepare_startable_game()
        player_sid = next(sid for sid, candidate in app.GAME["players"].items() if candidate["name"] == "One")
        player = app.GAME["players"][player_sid]
        app.GAME["board"][(5, 3)] = "river"
        player["birth_x"], player["birth_y"] = 5, 3
        player["x"], player["y"] = 5, 3
        player["items"]["boat"] = False
        player["items"]["raft"] = False

        app.apply_tile_effect(player)
        self.assertTrue(player["lost"])
        self.assertTrue(player["in_river"])
        self.assertEqual((player["x"], player["y"]), (6, 3))

        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)
        self.one.emit("player_move", {"direction": "left"})
        self.assertFalse(player["lost"])
        self.assertTrue(player["in_river"])
        self.assertEqual((player["x"], player["y"]), (5, 3))

        # On the next turn, going back into river_start must still be safe.
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)
        injuries_after_recovery = player["injuries"]
        self.one.emit("player_move", {"direction": "right"})

        self.assertEqual((player["x"], player["y"]), (6, 3))
        self.assertFalse(player["lost"])
        self.assertTrue(player["in_river"])
        self.assertEqual(player["injuries"], injuries_after_recovery)
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
        self.assertTrue(player["in_river"])
        app.GAME["current_turn_index"] = app.GAME["player_order"].index(player_sid)

        self.one.emit("player_move", {"direction": "left"})

        self.assertEqual((player["x"], player["y"]), (5, 3))
        self.assertFalse(player["lost"])
        self.assertTrue(player["in_river"])
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

    def test_starting_tile_effect_waits_for_that_players_first_turn(self):
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
        first_player = app.current_player()
        waiting_player = treasure_player if first_player["sid"] == devil_player["sid"] else devil_player

        if first_player["sid"] == devil_player["sid"]:
            self.assertEqual(devil_player["injuries"], 1)
            self.assertFalse(treasure_player["items"]["treasure"])
        else:
            self.assertTrue(treasure_player["items"]["treasure"])
            self.assertEqual(devil_player["injuries"], 0)
        self.assertTrue(waiting_player["spawn_effect_pending"])

        app.end_turn()

        self.assertEqual(devil_player["injuries"], 1)
        self.assertTrue(treasure_player["items"]["treasure"])
        self.assertIn((1, 0), app.GAME["consumed_tiles"])
        self.assertFalse(waiting_player["spawn_effect_pending"])


if __name__ == "__main__":
    unittest.main()
