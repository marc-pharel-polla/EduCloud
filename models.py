"""
Models SQLAlchemy pour Edu-Cloud IaaS
Version corrigée avec support multi-hôtes
"""
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import hashlib

Base = declarative_base()

# ========================================
# MODÈLES
# ========================================

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relations
    vms = relationship('VM', back_populates='user', cascade='all, delete-orphan')
    networks = relationship('Network', back_populates='user', cascade='all, delete-orphan')
    bills = relationship('Billing', back_populates='user', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class VM(Base):
    __tablename__ = 'vms'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(50), nullable=False)
    host_id = Column(String(50), nullable=False)
    flavor = Column(String(20), nullable=False)
    image = Column(String(50), nullable=False)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete='SET NULL'))
    status = Column(String(20), default='creating')
    created_at = Column(DateTime, default=datetime.now)
    
    # Relations
    user = relationship('User', back_populates='vms')
    network = relationship('Network')  # ✅ PAS de back_populates ici
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'display_name': self.display_name,
            'host_id': self.host_id,
            'flavor': self.flavor,
            'image': self.image,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Network(Base):
    __tablename__ = 'networks'
    
    # ✅ Contrainte d'unicité : un réseau par (user, host)
    __table_args__ = (
        UniqueConstraint('user_id', 'host_id', name='unique_user_host_network'),
    )
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), unique=True, nullable=False)
    subnet = Column(String(50), nullable=False)
    host_id = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    
    # ✅ Relation : Network → User seulement (PAS de relation vers VM)
    user = relationship('User', back_populates='networks')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'subnet': self.subnet,
            'host_id': self.host_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Billing(Base):
    __tablename__ = 'billing'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(255))
    vm_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relation
    user = relationship('User', back_populates='bills')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'amount': self.amount,
            'description': self.description,
            'vm_id': self.vm_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ========================================
# REPOSITORIES
# ========================================

class UserRepository:
    def __init__(self, session):
        self.session = session
    
    def get_all(self):
        """Liste TOUS les utilisateurs"""
        return self.session.query(User).all()
    
    def find_by_id(self, user_id):
        """Trouve un utilisateur par ID"""
        return self.session.query(User).filter_by(id=user_id).first()
    
    def find_by_username(self, username):
        """Trouve un utilisateur par username"""
        return self.session.query(User).filter_by(username=username).first()
    
    def create(self, username, password_hash, email=None, is_admin=False):
        """Crée un nouvel utilisateur"""
        user = User(
            username=username,
            password_hash=password_hash,
            email=email,
            is_admin=is_admin
        )
        self.session.add(user)
        self.session.commit()
        return user


class VMRepository:
    def __init__(self, session):
        self.session = session
    
    def find_by_user(self, user_id):
        """Trouve toutes les VMs d'un utilisateur"""
        return self.session.query(VM).filter_by(user_id=user_id).all()
    
    def find_by_name(self, name):
        """Trouve une VM par son nom"""
        return self.session.query(VM).filter_by(name=name).first()
    
    def find_by_display_name_and_user(self, display_name, user_id):
        """Trouve une VM par display_name et user_id"""
        return self.session.query(VM).filter_by(
            display_name=display_name,
            user_id=user_id
        ).first()
    
    def create(self, user_id, name, display_name, host_id, flavor, image, network_id, status='creating'):
        """Crée une nouvelle VM"""
        vm = VM(
            user_id=user_id,
            name=name,
            display_name=display_name,
            host_id=host_id,
            flavor=flavor,
            image=image,
            network_id=network_id,
            status=status
        )
        self.session.add(vm)
        self.session.commit()
        return vm
    
    def update_status(self, vm_id, status):
        """Met à jour le statut d'une VM"""
        vm = self.session.query(VM).filter_by(id=vm_id).first()
        if vm:
            vm.status = status
            self.session.commit()
    
    def delete(self, vm_id):
        """Supprime une VM"""
        vm = self.session.query(VM).filter_by(id=vm_id).first()
        if vm:
            self.session.delete(vm)
            self.session.commit()


class NetworkRepository:
    def __init__(self, session):
        self.session = session
    
    def find_by_user_and_host(self, user_id, host_id):
        """Trouve le réseau d'un utilisateur sur un hôte"""
        return self.session.query(Network).filter_by(
            user_id=user_id,
            host_id=host_id
        ).first()
    
    def create(self, user_id, name, subnet, host_id):
        """Crée un nouveau réseau"""
        network = Network(
            user_id=user_id,
            name=name,
            subnet=subnet,
            host_id=host_id
        )
        self.session.add(network)
        self.session.commit()
        return network


class BillingRepository:
    def __init__(self, session):
        self.session = session
    
    def find_by_user(self, user_id):
        """Trouve toutes les factures d'un utilisateur"""
        return self.session.query(Billing).filter_by(user_id=user_id).all()
    
    def get_total_by_user(self, user_id):
        """Calcule le total facturé pour un utilisateur"""
        from sqlalchemy import func
        result = self.session.query(func.sum(Billing.amount)).filter_by(user_id=user_id).scalar()
        return result or 0.0
    
    def create(self, user_id, amount, description, vm_id=None):
        """Crée une nouvelle entrée de facturation"""
        bill = Billing(
            user_id=user_id,
            amount=amount,
            description=description,
            vm_id=vm_id
        )
        self.session.add(bill)
        self.session.commit()
        return bill


# ========================================
# DATABASE
# ========================================

class Database:
    def __init__(self, database_url):
        self.engine = create_engine(database_url, echo=False)
        self.Session = sessionmaker(bind=self.engine)
    
    def create_tables(self):
        """Crée toutes les tables"""
        Base.metadata.create_all(self.engine)
    
    def get_session(self):
        """Retourne une nouvelle session"""
        return self.Session()


# ========================================
# SEED
# ========================================

def seed_database(db):
    """Initialise les données de base"""
    session = db.get_session()
    user_repo = UserRepository(session)
    
    # Créer l'admin si n'existe pas
    admin = user_repo.find_by_username('admin')
    if not admin:
        print("🔧 Création du compte admin...")
        admin = user_repo.create(
            username='admin',
            password_hash=hashlib.sha256('admin123'.encode()).hexdigest(),
            email='admin@educloud.local',
            is_admin=True
        )
        print(f"✅ Admin créé: {admin.username} (is_admin={admin.is_admin})")
    else:
        print(f"✅ Admin existe: {admin.username} (is_admin={admin.is_admin})")
        
        # Correction is_admin si nécessaire
        if not admin.is_admin:
            print("⚠️  Correction is_admin=True pour admin...")
            admin.is_admin = True
            session.commit()
            print("✅ Corrigé")
    
    session.close()