# Custom components

A **Custom Component** carries any of your game's components as a Rust type path and its data as JSON. To edit one with normal inputs instead, let your game list its components for Blender, or define the fields by hand.

## From your game

Add `BlenderSchemaPlugin` with your crate's name while you develop:

```rust
use bevy_components_importer::BlenderSchemaPlugin;

#[cfg(debug_assertions)]
app.add_plugins(BlenderSchemaPlugin::new(&["my_game"]));
```

Each run writes `bevy_components_schema.json` next to your `Cargo.toml`. It lists every component in those crates that derives `Reflect` with `#[reflect(Component)]`, with its fields and the defaults from `#[reflect(Default)]`. Blender finds the file in the [game project](play.md) folder or the folders above the .blend file, or set its path in the add-on preferences.

Your components then show under **Add Component**, in a menu named after your crate, with typed fields. Components already added as JSON switch to them and keep their values. When the components change, run the game again. Blender picks up the new file on its own, and **Properties > Scene > Bevy Custom Components** has a button to read it right away. Fields Blender cannot edit, such as a `Timer`, show as **Game default** and are left out, so the game needs `#[reflect(Default)]` to fill them in.

## By hand

1. In **Properties > Scene > Bevy Custom Components**, press **+** and double-click the new entry to set the type path, such as `my_game::Health`.
2. Add fields with a name, a type and a default. The default is used when the component is added to an object.
3. The type now appears under **Add Component**. Objects that already have it as JSON switch to the fields and keep their values.

**Define Fields** in a JSON component's dropdown does steps 1 and 2 for you from its data. **Edit as Text**, the button next to the JSON or in the dropdown, opens the data in a Text Editor; **Apply to Component** in its header writes it back. Changes to a definition reach every object that uses it, and removing a definition turns its components back into JSON with the same values. A type your game lists uses the game's fields instead.

## In the game

The importer inserts the component itself when your type derives `Reflect` with `#[reflect(Component)]`, found by its type path or by crate and type name, so `my_game::Health` also finds `my_game::stats::Health`, and a plain `Health` finds it when no other registered type has that name. Add `#[reflect(Default)]` to fill in fields the data leaves out. Other types arrive as JSON in `BlenderCustomComponents`, which `serde_json::from_value` reads into a struct with the same field names. Either way, the fields map to these Rust types:

| Field | Rust type |
| --- | --- |
| Float | `f32` |
| Integer | `i32` or another integer type |
| Boolean | `bool` |
| String | `String` |
| Vector 2D | `Vec2` |
| Vector | `Vec3`, on Bevy's axes (Y up) and not converted |
| Color | `Color`, in sRGB |
| Enum | An enum whose variants hold no data, such as `Team::Red` |

Fields named `0`, `1` and so on fill a tuple struct, such as `Reward(u32, f32)`.
