"""
Models SQLAlchemy - Équivalent de Prisma Schema pour Python
Remplace le code SQL brut par un ORM moderne
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool

Base = declarative_base()

# ========================================
# MODELS (comme schema.prisma)
# ========================================

class User(Base):
    """Modèle Utilisateur - Authentification multi-tenant"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    vms = relationship('VM', back_populates='user', cascade='all, delete-orphan')
    networks = relationship('Network', back_populates='user', cascade='all, delete-orphan')
    billing_records = relationship('Billing', back_populates='user', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Network(Base):
    """Modèle Réseau - Isolation par utilisateur"""
    __tablename__ = 'networks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), unique=True, nullable=False, index=True)
    subnet = Column(String(50), nullable=False)
    host_id = Column(String(50), nullable=False)
    type = Column(String(20), default='user')  # 'user' ou 'swarm'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    user = relationship('User', back_populates='networks')
    vms = relationship('VM', back_populates='network')
    
    def __repr__(self):
        return f"<Network(id={self.id}, name='{self.name}', subnet='{self.subnet}')>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'subnet': self.subnet,
            'host_id': self.host_id,
            'type': self.type,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class VM(Base):
    """Modèle Machine Virtuelle"""
    __tablename__ = 'vms'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), unique=True, nullable=False, index=True)
    host_id = Column(String(50), nullable=False)
    flavor = Column(String(10), nullable=False)
    image = Column(String(50), nullable=False)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete='SET NULL'))
    ip_address = Column(String(50))
    status = Column(String(20), default='creating')  # creating, running, stopped, error
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    user = relationship('User', back_populates='vms')
    network = relationship('Network', back_populates='vms')
    billing_records = relationship('Billing', back_populates='vm', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<VM(id={self.id}, name='{self.name}', status='{self.status}')>"
    
    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'host_id': self.host_id,
            'flavor': self.flavor,
            'image': self.image,
            'network_id': self.network_id,
            'ip_address': self.ip_address,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        if include_relations:
            if self.user:
                data['user'] = self.user.to_dict()
            if self.network:
                data['network'] = self.network.to_dict()
        
        return data


class Billing(Base):
    """Modèle Facturation"""
    __tablename__ = 'billing'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    vm_id = Column(Integer, ForeignKey('vms.id', ondelete='SET NULL'))
    amount = Column(Float, nullable=False)
    description = Column(String(255))
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    user = relationship('User', back_populates='billing_records')
    vm = relationship('VM', back_populates='billing_records')
    
    def __repr__(self):
        return f"<Billing(id={self.id}, amount={self.amount}, user_id={self.user_id})>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'vm_id': self.vm_id,
            'amount': round(self.amount, 2),
            'description': self.description,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ========================================
# DATABASE CONNECTION & SESSION
# ========================================

class Database:
    """Gestionnaire de base de données centralisé"""
    
    def __init__(self, database_url='sql:///Edu-Cloudduu_CL.db'):
        """
        Initialise la connexion à la base de données
        
        Args:
            database_url: URL de connexion (SQLite par défaut)
                         Exemples:
                         - sqlite:///iaas.db (SQLite local)
                         - postgresql://user:pass@localhost/iaas (PostgreSQL)
                         - mysql://user:pass@localhost/iaas (MySQL)
        """
        self.engine = create_engine(
            database_url,
            connect_args={'check_same_thread': False} if 'sqlite' in database_url else {},
            poolclass=StaticPool if 'sqlite' in database_url else None,
            echo=False  # Mettre True pour voir les requêtes SQL
        )
        
        self.SessionLocal = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        )
    
    def create_tables(self):
        """Crée toutes les tables (équivalent de prisma migrate)"""
        Base.metadata.create_all(bind=self.engine)
        print("✓ Tables créées/vérifiées")
    
    def drop_tables(self):
        """Supprime toutes les tables (ATTENTION: perte de données)"""
        Base.metadata.drop_all(bind=self.engine)
        print("✓ Tables supprimées")
    
    def get_session(self):
        """Retourne une nouvelle session de base de données"""
        return self.SessionLocal()
    
    def close(self):
        """Ferme toutes les connexions"""
        self.SessionLocal.remove()


# ========================================
# REPOSITORY PATTERN (abstraction de la DB)
# ========================================

class UserRepository:
    """Repository pour les opérations sur les utilisateurs"""
    
    def __init__(self, session):
        self.session = session
    
    def create(self, username, password_hash, email=None):
        """Crée un nouvel utilisateur"""
        user = User(username=username, password_hash=password_hash, email=email)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user
    
    def find_by_username(self, username):
        """Trouve un utilisateur par son username"""
        return self.session.query(User).filter(User.username == username).first()
    
    def find_by_id(self, user_id):
        """Trouve un utilisateur par son ID"""
        return self.session.query(User).filter(User.id == user_id).first()
    
    def list_all(self):
        """Liste tous les utilisateurs"""
        return self.session.query(User).all()


class VMRepository:
    """Repository pour les opérations sur les VMs"""
    
    def __init__(self, session):
        self.session = session
    
    def create(self, user_id, name, host_id, flavor, image, network_id=None, status='creating'):
        """Crée une nouvelle VM"""
        vm = VM(
            user_id=user_id,
            name=name,
            host_id=host_id,
            flavor=flavor,
            image=image,
            network_id=network_id,
            status=status
        )
        self.session.add(vm)
        self.session.commit()
        self.session.refresh(vm)
        return vm
    
    def find_by_name(self, name):
        """Trouve une VM par son nom"""
        return self.session.query(VM).filter(VM.name == name).first()
    
    def find_by_user(self, user_id):
        """Liste toutes les VMs d'un utilisateur"""
        return self.session.query(VM).filter(VM.user_id == user_id).all()
    
    def update_status(self, vm_id, status):
        """Met à jour le statut d'une VM"""
        vm = self.session.query(VM).filter(VM.id == vm_id).first()
        if vm:
            vm.status = status
            self.session.commit()
        return vm
    
    def update_ip(self, vm_id, ip_address):
        """Met à jour l'IP d'une VM"""
        vm = self.session.query(VM).filter(VM.id == vm_id).first()
        if vm:
            vm.ip_address = ip_address
            self.session.commit()
        return vm
    
    def delete(self, vm_id):
        """Supprime une VM"""
        vm = self.session.query(VM).filter(VM.id == vm_id).first()
        if vm:
            self.session.delete(vm)
            self.session.commit()
            return True
        return False


class NetworkRepository:
    """Repository pour les opérations sur les réseaux"""
    
    def __init__(self, session):
        self.session = session
    
    def create(self, user_id, name, subnet, host_id, network_type='user'):
        """Crée un nouveau réseau"""
        network = Network(
            user_id=user_id,
            name=name,
            subnet=subnet,
            host_id=host_id,
            type=network_type
        )
        self.session.add(network)
        self.session.commit()
        self.session.refresh(network)
        return network
    
    def find_by_user_and_host(self, user_id, host_id, network_type='user'):
        """Trouve le réseau d'un utilisateur sur un hôte"""
        return self.session.query(Network).filter(
            Network.user_id == user_id,
            Network.host_id == host_id,
            Network.type == network_type
        ).first()
    
    def find_by_name(self, name):
        """Trouve un réseau par son nom"""
        return self.session.query(Network).filter(Network.name == name).first()


class BillingRepository:
    """Repository pour les opérations de facturation"""
    
    def __init__(self, session):
        self.session = session
    
    def create(self, user_id, amount, description, vm_id=None, period_start=None, period_end=None):
        """Crée une entrée de facturation"""
        billing = Billing(
            user_id=user_id,
            vm_id=vm_id,
            amount=amount,
            description=description,
            period_start=period_start,
            period_end=period_end
        )
        self.session.add(billing)
        self.session.commit()
        self.session.refresh(billing)
        return billing
    
    def find_by_user(self, user_id, limit=100):
        """Liste les entrées de facturation d'un utilisateur"""
        return self.session.query(Billing).filter(
            Billing.user_id == user_id
        ).order_by(Billing.created_at.desc()).limit(limit).all()
    
    def get_total_by_user(self, user_id):
        """Calcule le total facturé pour un utilisateur"""
        from sqlalchemy import func
        result = self.session.query(func.sum(Billing.amount)).filter(
            Billing.user_id == user_id
        ).scalar()
        return result or 0.0


# ========================================
# SEED DATA (données initiales)
# ========================================

def seed_database(db: Database):
    """Crée les données initiales (utilisateur admin)"""
    session = db.get_session()
    user_repo = UserRepository(session)
    
    try:
        # Vérifier si admin existe
        admin = user_repo.find_by_username('admin')
        if not admin:
            # Créer l'utilisateur admin
            import hashlib
            password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
            admin = user_repo.create('admin', password_hash, 'admin@example.com')
            print(f"✓ Utilisateur admin créé (ID: {admin.id})")
        else:
            print(f"✓ Utilisateur admin existe déjà (ID: {admin.id})")
    finally:
        session.close()


# ========================================
# EXEMPLE D'UTILISATION
# ========================================

if __name__ == '__main__':
    # Initialiser la base de données
    db = Database('sql:///Edu-Cloud.db')
    
    # Créer les tables
    db.create_tables()
    
    # Données initiales
    seed_database(db)
    
    # Exemple d'utilisation
    session = db.get_session()
    
    try:
        # Créer un utilisateur
        user_repo = UserRepository(session)
        user = user_repo.find_by_username('admin')
        print(f"\nUtilisateur: {user}")
        
        # Créer un réseau
        network_repo = NetworkRepository(session)
        network = network_repo.create(
            user_id=user.id,
            name=f'net-user-{user.id}',
            subnet=f'10.{100 + user.id}.0.0/24',
            host_id='local'
        )
        print(f"Réseau créé: {network}")
        
        # Créer une VM
        vm_repo = VMRepository(session)
        vm = vm_repo.create(
            user_id=user.id,
            name='test-vm',
            host_id='local',
            flavor='M',
            image='ubuntu-22.04',
            network_id=network.id,
            status='running'
        )
        print(f"VM créée: {vm}")
        
        # Créer une facturation
        billing_repo = BillingRepository(session)
        billing = billing_repo.create(
            user_id=user.id,
            vm_id=vm.id,
            amount=4.79,
            description=f'VM {vm.name} - flavor M'
        )
        print(f"Facturation: {billing}")
        
        # Lister les VMs de l'utilisateur
        vms = vm_repo.find_by_user(user.id)
        print(f"\nVMs de {user.username}:")
        for v in vms:
            print(f"  - {v.name} ({v.status})")
        
        # Total facturation
        total = billing_repo.get_total_by_user(user.id)
        print(f"\nTotal facturé: {total} FCFA")
        
    finally:
        session.close()
        db.close()
    
    print("\n✓ Exemple terminé")