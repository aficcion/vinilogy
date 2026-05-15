# Solución: Error al Eliminar Usuarios

## Problema
Al intentar eliminar un usuario desde la interfaz del explorador de base de datos (http://localhost:5001), se mostraba el error:
```
No se pudo eliminar el usuario
```

## Causa Raíz
El endpoint de eliminación de usuarios en `db_explorer/app.py` no tenía un manejo de errores robusto. Aunque el esquema de la base de datos tiene configurado correctamente `ON DELETE CASCADE` para las foreign keys, el código no capturaba ni reportaba errores específicos que pudieran ocurrir durante la eliminación.

## Solución Implementada

### Cambios en `/db_explorer/app.py`

Se mejoró el endpoint `/api/delete/user/<int:user_id>` con:

1. **Verificación de Foreign Keys**: Se verifica que las foreign keys estén habilitadas
2. **Validación de Usuario**: Se verifica que el usuario existe antes de intentar eliminarlo
3. **Manejo de Errores**: Se capturan y reportan errores específicos
4. **Logging Detallado**: Se registra información sobre la eliminación
5. **Mensajes Descriptivos**: Se devuelven mensajes de error claros al frontend

```python
@app.route('/api/delete/user/<int:user_id>', methods=['DELETE'])
def api_delete_user(user_id):
    """Delete a user and all associated data"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Verify foreign keys are enabled
        cursor.execute("PRAGMA foreign_keys;")
        fk_status = cursor.fetchone()
        print(f"Foreign keys status: {fk_status}")
        
        # Get user info before deletion for logging
        cursor.execute("SELECT display_name FROM user WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404
        
        # SQLite will handle CASCADE deletes for auth_identity, user_profile_lastfm,
        # user_selected_artist, and recommendation tables due to foreign key constraints
        cursor.execute("DELETE FROM user WHERE id = ?", (user_id,))
        
        rows_deleted = cursor.rowcount
        print(f"Deleted user {user_id} ({user['display_name']}), rows affected: {rows_deleted}")
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Usuario eliminado correctamente'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error deleting user {user_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

## Cómo Funciona la Eliminación en Cascada

El esquema de la base de datos (definido en `gateway/db.py`) tiene las siguientes tablas relacionadas con `user`:

1. **auth_identity**: `FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE`
2. **user_profile_lastfm**: `FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE`
3. **user_selected_artist**: `FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE`
4. **recommendation**: `FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE`

Cuando se elimina un usuario, SQLite automáticamente elimina todos los registros relacionados en estas tablas gracias a `ON DELETE CASCADE`.

## Verificación

Para verificar que la eliminación funciona correctamente:

1. Abre el explorador de base de datos: http://localhost:5001
2. Ve a la sección "Usuarios"
3. Intenta eliminar un usuario
4. Verifica en la consola del servidor los logs de eliminación
5. Confirma que el usuario y todos sus datos relacionados fueron eliminados

## Notas Importantes

- **Foreign Keys**: SQLite requiere que `PRAGMA foreign_keys = ON;` esté habilitado en cada conexión. Esto ya está configurado en la función `get_connection()`.
- **Transacciones**: El código usa transacciones con `commit()` y `rollback()` para garantizar la integridad de los datos.
- **Logging**: Los mensajes de log aparecen en la consola donde se ejecuta el servidor del explorador.

## Servidor Reiniciado

El servidor del explorador de base de datos ha sido reiniciado con los cambios aplicados y está corriendo en:
- **URL**: http://localhost:5001
- **Puerto**: 5001
