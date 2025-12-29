"""
Script pour nettoyer la base de données Neo4j
Supprime tous les nœuds et relations pour repartir à zéro
"""

from neo4j_manager import create_neo4j_manager

def clean_database():
    """
    Supprime TOUS les nœuds et relations de la base de données Neo4j.
    ⚠️ ATTENTION : Cette action est irréversible !
    """
    manager = create_neo4j_manager()
    
    if not manager.is_available():
        print("❌ Neo4j n'est pas disponible. Vérifiez votre connexion.")
        return
    
    print("=" * 60)
    print("🧹 NETTOYAGE DE LA BASE DE DONNÉES NEO4J")
    print("=" * 60)
    
    # Demander confirmation
    print("\n⚠️  ATTENTION : Vous êtes sur le point de supprimer")
    print("    TOUS les nœuds et relations de la base de données !")
    print()
    response = input("Tapez 'OUI' en majuscules pour confirmer : ")
    
    if response != "OUI":
        print("\n❌ Opération annulée.")
        manager.close()
        return
    
    try:
        with manager.driver.session() as session:
            # Compter les nœuds avant suppression
            print("\n📊 État avant nettoyage...")
            
            result = session.run("MATCH (d:Device) RETURN count(d) as count")
            device_count = result.single()["count"]
            print(f"   - Devices: {device_count}")
            
            result = session.run("MATCH (s:Scan) RETURN count(s) as count")
            scan_count = result.single()["count"]
            print(f"   - Scans: {scan_count}")
            
            result = session.run("MATCH (n:Network) RETURN count(n) as count")
            network_count = result.single()["count"]
            print(f"   - Networks: {network_count}")
            
            result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            relation_count = result.single()["count"]
            print(f"   - Relations: {relation_count}")
            
            total = device_count + scan_count + network_count
            print(f"\n   📍 Total à supprimer: {total} nœuds, {relation_count} relations")
            
            # Suppression
            print("\n🗑️  Suppression en cours...")
            session.run("MATCH (n) DETACH DELETE n")
            
            # Vérification
            result = session.run("MATCH (n) RETURN count(n) as count")
            remaining = result.single()["count"]
            
            if remaining == 0:
                print("\n✅ Base de données nettoyée avec succès !")
                print(f"   - {total} nœuds supprimés")
                print(f"   - {relation_count} relations supprimées")
                print("\n💡 La base de données est maintenant vide et prête")
                print("   pour de nouveaux scans.")
            else:
                print(f"\n⚠️  {remaining} nœuds restants (vérification requise)")
                
    except Exception as e:
        print(f"\n❌ Erreur lors du nettoyage: {e}")
    finally:
        manager.close()

def clean_only_old_scans(keep_latest=5):
    """
    Supprime uniquement les anciens scans, en gardant les N derniers.
    Les devices sont conservés mais les relations vers les vieux scans sont supprimées.
    """
    manager = create_neo4j_manager()
    
    if not manager.is_available():
        print("❌ Neo4j n'est pas disponible.")
        return
    
    print("=" * 60)
    print(f"🧹 NETTOYAGE DES ANCIENS SCANS (Garder les {keep_latest} derniers)")
    print("=" * 60)
    
    try:
        with manager.driver.session() as session:
            # Identifier les scans à supprimer
            query = f"""
            MATCH (s:Scan)
            WITH s
            ORDER BY s.timestamp DESC
            SKIP {keep_latest}
            RETURN count(s) as count
            """
            result = session.run(query)
            to_delete = result.single()["count"]
            
            print(f"\n📊 Scans à supprimer: {to_delete}")
            
            if to_delete == 0:
                print("✅ Aucun ancien scan à supprimer.")
                manager.close()
                return
            
            response = input(f"\nConfirmer la suppression de {to_delete} scans ? (oui/non) : ")
            
            if response.lower() != "oui":
                print("❌ Opération annulée.")
                manager.close()
                return
            
            # Supprimer les anciens scans
            delete_query = f"""
            MATCH (s:Scan)
            WITH s
            ORDER BY s.timestamp DESC
            SKIP {keep_latest}
            DETACH DELETE s
            """
            session.run(delete_query)
            
            print(f"\n✅ {to_delete} anciens scans supprimés !")
            print(f"   Les {keep_latest} scans les plus récents sont conservés.")
            
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
    finally:
        manager.close()

if __name__ == "__main__":
    print("\n🛠️  UTILITAIRE DE NETTOYAGE NEO4J")
    print("\nChoisissez une option:")
    print("  1 - Nettoyer TOUTE la base de données (tout supprimer)")
    print("  2 - Supprimer uniquement les anciens scans (garder les 5 derniers)")
    print("  3 - Annuler")
    
    choice = input("\nVotre choix (1/2/3) : ")
    
    if choice == "1":
        clean_database()
    elif choice == "2":
        try:
            keep = int(input("Combien de scans récents garder ? (défaut: 5) : ") or "5")
            clean_only_old_scans(keep)
        except:
            print("❌ Nombre invalide, opération annulée.")
    else:
        print("❌ Opération annulée.")
